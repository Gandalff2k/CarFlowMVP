import asyncio
import datetime as dt
import uuid

import httpx
import pytest
from aiokafka import AIOKafkaProducer
from sqlalchemy import text

from services.auth.security import create_token
from services.booking.app import create_app as create_booking_app
from services.booking.config import BookingSettings
from services.booking.consumers import PAYMENT_EVENT_HANDLERS
from services.booking.listing_client import ListingClient
from services.listing.app import create_app as create_listing_app
from services.listing.config import ListingSettings
from services.payment.config import PaymentSettings
from services.payment.consumers import build_booking_command_handlers
from services.payment.stripe_client import StripeError
from shared.db import create_engine, create_session_factory
from shared.kafka_consumer import postgres_inbox_processor, run_consumer

SECRET = "test-secret"
ISSUER = "carflow-auth"
START = dt.date(2026, 6, 1)
END = dt.date(2026, 6, 4)


class FakeStripeClient:
    """The one true external in this saga (per CLAUDE.md, only Stripe/KYC/push
    get mocked); everything else in this test — Postgres, Kafka, both real
    consumer loops — is real."""

    def __init__(self, *, fail_authorize: bool = False) -> None:
        self.fail_authorize = fail_authorize

    def authorize(self, *, amount_cents, idempotency_key):
        if self.fail_authorize:
            raise StripeError("card declined")
        return "pi_test_123"

    def capture(self, *, payment_intent_id, amount_cents, idempotency_key):
        return None

    def authorize_and_capture(self, *, amount_cents, idempotency_key):
        return "pi_overage_test_123"


def _token(*, role: str, user_id: uuid.UUID | None = None) -> str:
    return create_token(
        user_id=user_id or uuid.uuid4(),
        role=role,
        token_type="access",
        secret=SECRET,
        issuer=ISSUER,
        ttl_seconds=900,
    )


def _headers(token: str, idempotency_key: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return headers


async def _ship_outbox_rows(
    database_url: str, *, bootstrap_servers: str, topic: str, aggregate_id: str
) -> int:
    """Stands in for Debezium's CDC capture in this test: reads and clears
    the real outbox table the app code wrote to, and republishes each row's
    payload verbatim onto the given Kafka topic via a real producer. What
    happens on either side of this call — the outbox write, the consumer
    that reads the topic — is exactly the production code path.

    Scoped to one aggregate_id because the booking/payment test databases are
    session-scoped and shared with other test modules: without this filter,
    a leftover outbox row from an unrelated booking created elsewhere in the
    session gets shipped too, and payment/booking would process a command for
    a booking this test never touched.
    """
    engine = create_engine(database_url)
    session_factory = create_session_factory(engine)
    producer = AIOKafkaProducer(bootstrap_servers=bootstrap_servers)
    await producer.start()
    shipped = 0
    try:
        async with session_factory() as session:
            rows = (
                await session.execute(
                    text(
                        "SELECT id, payload::text AS payload FROM outbox "
                        "WHERE aggregateid = :aggregate_id"
                    ),
                    {"aggregate_id": aggregate_id},
                )
            ).all()
            for row in rows:
                await producer.send_and_wait(topic, row.payload.encode())
                shipped += 1
                await session.execute(text("DELETE FROM outbox WHERE id = :id"), {"id": row.id})
            await session.commit()
    finally:
        await producer.stop()
    return shipped


async def _run_consumer_briefly(coro_factory, *, timeout: float = 5.0) -> None:
    task = asyncio.create_task(coro_factory())
    await asyncio.sleep(timeout)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _run_payment_consumer_once(
    payment_database_url: str, *, bootstrap_servers: str, topic: str, stripe_client
) -> None:
    engine = create_engine(payment_database_url)
    session_factory = create_session_factory(engine)
    await _run_consumer_briefly(
        lambda: run_consumer(
            bootstrap_servers=bootstrap_servers,
            topic=topic,
            group_id="payment-test",
            process=postgres_inbox_processor(
                session_factory, build_booking_command_handlers(stripe_client)
            ),
            tracer_name="payment-test",
        )
    )


async def _run_booking_consumer_once(
    booking_database_url: str, *, bootstrap_servers: str, topic: str
) -> None:
    engine = create_engine(booking_database_url)
    session_factory = create_session_factory(engine)
    await _run_consumer_briefly(
        lambda: run_consumer(
            bootstrap_servers=bootstrap_servers,
            topic=topic,
            group_id="booking-test",
            process=postgres_inbox_processor(session_factory, PAYMENT_EVENT_HANDLERS),
            tracer_name="booking-test",
        )
    )


@pytest.fixture()
async def listing_client(listing_database_url: str):
    settings = ListingSettings(
        service_name="listing-test",
        database_url=listing_database_url,
        otel_exporter_otlp_endpoint="",
        jwt_secret=SECRET,
        jwt_issuer=ISSUER,
    )
    transport = httpx.ASGITransport(app=create_listing_app(settings))
    async with httpx.AsyncClient(transport=transport, base_url="http://listing") as http_client:
        yield http_client


@pytest.fixture()
async def booking_client(booking_database_url: str, listing_client: httpx.AsyncClient):
    settings = BookingSettings(
        service_name="booking-test",
        database_url=booking_database_url,
        otel_exporter_otlp_endpoint="",
        jwt_secret=SECRET,
        jwt_issuer=ISSUER,
        enable_kafka_consumer=False,
    )
    booking_app = create_booking_app(
        settings, listing_client=ListingClient("http://listing", client=listing_client)
    )
    transport = httpx.ASGITransport(app=booking_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://booking") as http_client:
        yield http_client


async def _create_approved_vehicle(listing_client: httpx.AsyncClient) -> dict:
    host_token = _token(role="host")
    created = (
        await listing_client.post(
            "/listing/vehicles",
            json={
                "make": "Toyota",
                "model": "Corolla",
                "year": 2020,
                "daily_price_cents": 5000,
                "daily_mileage_limit": 200,
                "booking_mode": "instant",
                "latitude": 40.7128,
                "longitude": -74.0060,
            },
            headers=_headers(host_token, str(uuid.uuid4())),
        )
    ).json()
    await listing_client.post(
        f"/listing/vehicles/{created['id']}/approve",
        headers=_headers(_token(role="admin"), str(uuid.uuid4())),
    )
    return created


async def test_authorization_success_confirms_the_booking_over_real_kafka(
    booking_client: httpx.AsyncClient,
    listing_client: httpx.AsyncClient,
    booking_database_url: str,
    payment_database_url: str,
    kafka_bootstrap_servers: str,
) -> None:
    vehicle = await _create_approved_vehicle(listing_client)
    booking = (
        await booking_client.post(
            "/booking/bookings",
            json={"vehicle_id": vehicle["id"], "start_date": str(START), "end_date": str(END)},
            headers=_headers(_token(role="renter"), str(uuid.uuid4())),
        )
    ).json()
    assert booking["status"] == "requested"

    commands_topic = PaymentSettings().booking_commands_topic
    events_topic = PaymentSettings().booking_events_topic

    await _ship_outbox_rows(
        booking_database_url,
        bootstrap_servers=kafka_bootstrap_servers,
        topic=commands_topic,
        aggregate_id=booking["id"],
    )
    await _run_payment_consumer_once(
        payment_database_url,
        bootstrap_servers=kafka_bootstrap_servers,
        topic=commands_topic,
        stripe_client=FakeStripeClient(),
    )
    await _ship_outbox_rows(
        payment_database_url,
        bootstrap_servers=kafka_bootstrap_servers,
        topic=events_topic,
        aggregate_id=booking["id"],
    )
    await _run_booking_consumer_once(
        booking_database_url, bootstrap_servers=kafka_bootstrap_servers, topic=events_topic
    )

    confirmed = (
        await booking_client.get(
            f"/booking/bookings/{booking['id']}", headers=_headers(_token(role="admin"))
        )
    ).json()
    assert confirmed["status"] == "confirmed"


async def test_authorization_failure_cancels_the_booking_compensation_path(
    booking_client: httpx.AsyncClient,
    listing_client: httpx.AsyncClient,
    booking_database_url: str,
    payment_database_url: str,
    kafka_bootstrap_servers: str,
) -> None:
    vehicle = await _create_approved_vehicle(listing_client)
    booking = (
        await booking_client.post(
            "/booking/bookings",
            json={"vehicle_id": vehicle["id"], "start_date": str(START), "end_date": str(END)},
            headers=_headers(_token(role="renter"), str(uuid.uuid4())),
        )
    ).json()

    commands_topic = "booking.payment.commands.fail-test"
    events_topic = "payment.booking.events.fail-test"

    await _ship_outbox_rows(
        booking_database_url,
        bootstrap_servers=kafka_bootstrap_servers,
        topic=commands_topic,
        aggregate_id=booking["id"],
    )
    await _run_payment_consumer_once(
        payment_database_url,
        bootstrap_servers=kafka_bootstrap_servers,
        topic=commands_topic,
        stripe_client=FakeStripeClient(fail_authorize=True),
    )
    await _ship_outbox_rows(
        payment_database_url,
        bootstrap_servers=kafka_bootstrap_servers,
        topic=events_topic,
        aggregate_id=booking["id"],
    )
    await _run_booking_consumer_once(
        booking_database_url, bootstrap_servers=kafka_bootstrap_servers, topic=events_topic
    )

    cancelled = (
        await booking_client.get(
            f"/booking/bookings/{booking['id']}", headers=_headers(_token(role="admin"))
        )
    ).json()
    assert cancelled["status"] == "cancelled"
