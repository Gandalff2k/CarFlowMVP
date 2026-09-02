import datetime as dt
import uuid

import httpx
import pytest

from services.auth.security import create_token
from services.booking.app import create_app as create_booking_app
from services.booking.config import BookingSettings
from services.booking.listing_client import ListingClient
from services.booking.repository import BookingRepository
from services.booking.service import apply_payment_authorized
from services.listing.app import create_app as create_listing_app
from services.listing.config import ListingSettings
from shared.db import create_engine, create_session_factory

SECRET = "test-secret"
ISSUER = "carflow-auth"

START = dt.date(2026, 6, 1)
END = dt.date(2026, 6, 4)


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
async def approved_vehicle(listing_client: httpx.AsyncClient) -> dict:
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
            },
            headers=_headers(host_token, str(uuid.uuid4())),
        )
    ).json()
    await listing_client.post(
        f"/listing/vehicles/{created['id']}/approve",
        headers=_headers(_token(role="admin"), str(uuid.uuid4())),
    )
    return {"id": created["id"], "host_id": created["host_id"]}


@pytest.fixture()
async def request_mode_vehicle(listing_client: httpx.AsyncClient) -> dict:
    host_token = _token(role="host")
    created = (
        await listing_client.post(
            "/listing/vehicles",
            json={
                "make": "Honda",
                "model": "Civic",
                "year": 2021,
                "daily_price_cents": 4000,
                "daily_mileage_limit": 150,
                "booking_mode": "request",
            },
            headers=_headers(host_token, str(uuid.uuid4())),
        )
    ).json()
    await listing_client.post(
        f"/listing/vehicles/{created['id']}/approve",
        headers=_headers(_token(role="admin"), str(uuid.uuid4())),
    )
    return {"id": created["id"], "host_id": created["host_id"], "host_token": host_token}


@pytest.fixture()
async def client(booking_database_url: str, listing_client: httpx.AsyncClient):
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


@pytest.fixture()
def confirm_payment(booking_database_url: str):
    engine = create_engine(booking_database_url)
    session_factory = create_session_factory(engine)

    async def _confirm(booking_id: str) -> None:
        async with session_factory() as session:
            await apply_payment_authorized(
                BookingRepository(session), booking_id=uuid.UUID(booking_id)
            )
            await session.commit()

    return _confirm


async def test_renter_requests_instant_booking_on_approved_vehicle(
    client: httpx.AsyncClient, approved_vehicle: dict
) -> None:
    response = await client.post(
        "/booking/bookings",
        json={
            "vehicle_id": approved_vehicle["id"],
            "start_date": str(START),
            "end_date": str(END),
        },
        headers=_headers(_token(role="renter"), str(uuid.uuid4())),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "requested"
    assert body["booking_mode"] == "instant"
    assert body["host_id"] == approved_vehicle["host_id"]


async def test_host_cannot_request_a_booking(
    client: httpx.AsyncClient, approved_vehicle: dict
) -> None:
    response = await client.post(
        "/booking/bookings",
        json={
            "vehicle_id": approved_vehicle["id"],
            "start_date": str(START),
            "end_date": str(END),
        },
        headers=_headers(_token(role="host"), str(uuid.uuid4())),
    )

    assert response.status_code == 403


async def test_booking_rejects_a_vehicle_that_is_not_approved(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/booking/bookings",
        json={
            "vehicle_id": str(uuid.uuid4()),
            "start_date": str(START),
            "end_date": str(END),
        },
        headers=_headers(_token(role="renter"), str(uuid.uuid4())),
    )

    assert response.status_code == 404


async def test_overlapping_bookings_for_the_same_vehicle_conflict(
    client: httpx.AsyncClient, approved_vehicle: dict
) -> None:
    body = {
        "vehicle_id": approved_vehicle["id"],
        "start_date": str(START),
        "end_date": str(END),
    }
    first = await client.post(
        "/booking/bookings", json=body, headers=_headers(_token(role="renter"), str(uuid.uuid4()))
    )
    overlapping = await client.post(
        "/booking/bookings",
        json={**body, "start_date": "2026-06-03", "end_date": "2026-06-06"},
        headers=_headers(_token(role="renter"), str(uuid.uuid4())),
    )

    assert first.status_code == 201
    assert overlapping.status_code == 409


async def test_create_booking_is_idempotent_under_key_replay(
    client: httpx.AsyncClient, approved_vehicle: dict
) -> None:
    key = str(uuid.uuid4())
    body = {
        "vehicle_id": approved_vehicle["id"],
        "start_date": str(START),
        "end_date": str(END),
    }
    renter_token = _token(role="renter")

    first = await client.post("/booking/bookings", json=body, headers=_headers(renter_token, key))
    second = await client.post("/booking/bookings", json=body, headers=_headers(renter_token, key))

    assert first.status_code == second.status_code == 201
    assert first.json() == second.json()


async def test_request_mode_booking_waits_for_host_before_confirming(
    client: httpx.AsyncClient, request_mode_vehicle: dict
) -> None:
    created = (
        await client.post(
            "/booking/bookings",
            json={
                "vehicle_id": request_mode_vehicle["id"],
                "start_date": str(START),
                "end_date": str(END),
            },
            headers=_headers(_token(role="renter"), str(uuid.uuid4())),
        )
    ).json()

    accepted = await client.post(
        f"/booking/bookings/{created['id']}/accept",
        headers=_headers(request_mode_vehicle["host_token"], str(uuid.uuid4())),
    )

    assert created["status"] == "requested"
    assert accepted.status_code == 200


async def test_only_the_vehicles_host_can_accept_a_request(
    client: httpx.AsyncClient, request_mode_vehicle: dict
) -> None:
    created = (
        await client.post(
            "/booking/bookings",
            json={
                "vehicle_id": request_mode_vehicle["id"],
                "start_date": str(START),
                "end_date": str(END),
            },
            headers=_headers(_token(role="renter"), str(uuid.uuid4())),
        )
    ).json()

    response = await client.post(
        f"/booking/bookings/{created['id']}/accept",
        headers=_headers(_token(role="host"), str(uuid.uuid4())),
    )

    assert response.status_code == 403


async def test_host_rejects_a_request_mode_booking(
    client: httpx.AsyncClient, request_mode_vehicle: dict
) -> None:
    created = (
        await client.post(
            "/booking/bookings",
            json={
                "vehicle_id": request_mode_vehicle["id"],
                "start_date": str(START),
                "end_date": str(END),
            },
            headers=_headers(_token(role="renter"), str(uuid.uuid4())),
        )
    ).json()

    rejected = await client.post(
        f"/booking/bookings/{created['id']}/reject",
        headers=_headers(request_mode_vehicle["host_token"], str(uuid.uuid4())),
    )

    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


async def test_a_stranger_cannot_view_a_booking(
    client: httpx.AsyncClient, approved_vehicle: dict
) -> None:
    created = (
        await client.post(
            "/booking/bookings",
            json={
                "vehicle_id": approved_vehicle["id"],
                "start_date": str(START),
                "end_date": str(END),
            },
            headers=_headers(_token(role="renter"), str(uuid.uuid4())),
        )
    ).json()

    response = await client.get(
        f"/booking/bookings/{created['id']}", headers=_headers(_token(role="renter"))
    )

    assert response.status_code == 403


async def test_full_saga_reaches_completed_with_overage_charged(
    client: httpx.AsyncClient, approved_vehicle: dict, confirm_payment
) -> None:
    renter_token = _token(role="renter")
    host_token = _token(role="host", user_id=uuid.UUID(approved_vehicle["host_id"]))

    created = (
        await client.post(
            "/booking/bookings",
            json={
                "vehicle_id": approved_vehicle["id"],
                "start_date": str(START),
                "end_date": str(END),
            },
            headers=_headers(renter_token, str(uuid.uuid4())),
        )
    ).json()

    await confirm_payment(created["id"])

    handed_over = await client.post(
        f"/booking/bookings/{created['id']}/handover",
        json={"odometer": 1000, "fuel_percent": 100, "photo_url": "http://x/1.jpg"},
        headers=_headers(host_token, str(uuid.uuid4())),
    )
    returned = await client.post(
        f"/booking/bookings/{created['id']}/return",
        json={"odometer": 1700, "fuel_percent": 40, "photo_url": "http://x/2.jpg"},
        headers=_headers(host_token, str(uuid.uuid4())),
    )

    assert handed_over.status_code == 200
    assert handed_over.json()["status"] == "active"
    assert returned.status_code == 200
    # allowance = 200 * 3 days = 600 miles; drove 700 -> 100 miles over.
    assert returned.json()["overage_cents"] == 100 * 50
