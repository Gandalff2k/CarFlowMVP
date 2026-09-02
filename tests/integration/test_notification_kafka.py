import asyncio
import json
import uuid

from aiokafka import AIOKafkaProducer

from services.notification.consumers import BOOKING_EVENT_HANDLERS
from services.notification.models import NotificationPreference
from shared.db import create_engine, create_session_factory
from shared.kafka_consumer import postgres_inbox_processor, run_consumer


def _envelope(event_type: str, data: dict) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "data": data,
        "trace_context": {},
    }


async def _run_consumer_briefly(coro_factory, *, timeout: float = 5.0) -> None:
    task = asyncio.create_task(coro_factory())
    await asyncio.sleep(timeout)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def _insert_preference(session_factory, *, user_id: uuid.UUID, sms_enabled: bool) -> None:
    async with session_factory() as session:
        session.add(NotificationPreference(user_id=user_id, sms_enabled=sms_enabled))
        await session.commit()


async def test_booking_confirmed_notifies_renter_and_host_with_default_preferences(
    notification_database_url: str, kafka_bootstrap_servers: str, caplog
) -> None:
    topic = f"booking.events.test-{uuid.uuid4().hex}"
    renter_id = uuid.uuid4()
    host_id = uuid.uuid4()
    booking_id = str(uuid.uuid4())

    producer = AIOKafkaProducer(bootstrap_servers=kafka_bootstrap_servers)
    await producer.start()
    try:
        envelope = _envelope(
            "booking_confirmed",
            {"booking_id": booking_id, "renter_id": str(renter_id), "host_id": str(host_id)},
        )
        await producer.send_and_wait(topic, json.dumps(envelope).encode())
    finally:
        await producer.stop()

    engine = create_engine(notification_database_url)
    session_factory = create_session_factory(engine)
    with caplog.at_level("INFO"):
        await _run_consumer_briefly(
            lambda: run_consumer(
                bootstrap_servers=kafka_bootstrap_servers,
                topic=topic,
                group_id="notification-test",
                process=postgres_inbox_processor(session_factory, BOOKING_EVENT_HANDLERS),
                tracer_name="notification-test",
            )
        )

    messages = " ".join(r.message for r in caplog.records)
    assert f"channel=email user_id={renter_id}" in messages
    assert f"channel=sms user_id={renter_id}" in messages
    assert f"channel=email user_id={host_id}" in messages
    assert f"channel=sms user_id={host_id}" in messages


async def test_a_user_with_sms_disabled_only_gets_an_email_would_send(
    notification_database_url: str, kafka_bootstrap_servers: str, caplog
) -> None:
    topic = f"booking.events.test-{uuid.uuid4().hex}"
    renter_id = uuid.uuid4()
    host_id = uuid.uuid4()
    booking_id = str(uuid.uuid4())

    engine = create_engine(notification_database_url)
    session_factory = create_session_factory(engine)
    await _insert_preference(session_factory, user_id=renter_id, sms_enabled=False)

    producer = AIOKafkaProducer(bootstrap_servers=kafka_bootstrap_servers)
    await producer.start()
    try:
        envelope = _envelope(
            "booking_cancelled",
            {"booking_id": booking_id, "renter_id": str(renter_id), "host_id": str(host_id)},
        )
        await producer.send_and_wait(topic, json.dumps(envelope).encode())
    finally:
        await producer.stop()

    with caplog.at_level("INFO"):
        await _run_consumer_briefly(
            lambda: run_consumer(
                bootstrap_servers=kafka_bootstrap_servers,
                topic=topic,
                group_id="notification-test",
                process=postgres_inbox_processor(session_factory, BOOKING_EVENT_HANDLERS),
                tracer_name="notification-test",
            )
        )

    messages = " ".join(r.message for r in caplog.records)
    assert f"channel=email user_id={renter_id}" in messages
    assert f"channel=sms user_id={renter_id}" not in messages
    assert f"channel=sms user_id={host_id}" in messages
