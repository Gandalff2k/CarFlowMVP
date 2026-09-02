import asyncio
import json
import uuid

from aiokafka import AIOKafkaProducer
from redis.asyncio import Redis

from services.search.consumers import build_listing_event_processor
from services.search.es_client import create_es_client, ensure_index
from services.search.repository import SearchRepository
from shared.kafka_consumer import run_consumer


def _envelope(event_type: str, data: dict, *, event_id: str | None = None) -> dict:
    return {
        "event_id": event_id or str(uuid.uuid4()),
        "event_type": event_type,
        "data": data,
        "trace_context": {},
    }


def _vehicle(**overrides) -> dict:
    data = {
        "vehicle_id": str(uuid.uuid4()),
        "host_id": str(uuid.uuid4()),
        "make": "Toyota",
        "model": "Corolla",
        "year": 2020,
        "daily_price_cents": 5000,
        "daily_mileage_limit": 200,
        "booking_mode": "instant",
        "approval_status": "approved",
        "latitude": 40.7128,
        "longitude": -74.0060,
    }
    data.update(overrides)
    return data


async def _run_consumer_briefly(coro_factory, *, timeout: float = 5.0) -> None:
    task = asyncio.create_task(coro_factory())
    await asyncio.sleep(timeout)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


async def test_vehicle_approved_event_is_indexed_over_real_kafka(
    kafka_bootstrap_servers: str, elasticsearch_url: str, redis_url: str
) -> None:
    index_name = f"vehicles-test-{uuid.uuid4().hex}"
    topic = f"listing.vehicle.events.test-{uuid.uuid4().hex}"

    es = create_es_client(elasticsearch_url)
    await ensure_index(es, index_name)
    repo = SearchRepository(es, index_name)
    redis = Redis.from_url(redis_url)

    vehicle = _vehicle()
    producer = AIOKafkaProducer(bootstrap_servers=kafka_bootstrap_servers)
    await producer.start()
    try:
        envelope = _envelope("vehicle_approved", vehicle)
        await producer.send_and_wait(topic, json.dumps(envelope).encode())
    finally:
        await producer.stop()

    await _run_consumer_briefly(
        lambda: run_consumer(
            bootstrap_servers=kafka_bootstrap_servers,
            topic=topic,
            group_id="search-test",
            process=build_listing_event_processor(redis, repo),
            tracer_name="search-test",
        )
    )
    await es.indices.refresh(index=index_name)

    result = await repo.search(make="Toyota")
    await es.close()
    await redis.aclose()

    assert any(doc["vehicle_id"] == vehicle["vehicle_id"] for doc in result)


async def test_duplicate_event_id_is_only_applied_once(redis_url: str) -> None:
    redis = Redis.from_url(redis_url)
    upserted: list[str] = []

    class CountingRepository:
        async def upsert_vehicle(self, vehicle_id, document):
            upserted.append(vehicle_id)

        async def delete_vehicle(self, vehicle_id):
            pass

    vehicle = _vehicle()
    process = build_listing_event_processor(redis, CountingRepository())
    event_id = str(uuid.uuid4())

    await process(event_id, "vehicle_approved", vehicle)
    await process(event_id, "vehicle_approved", vehicle)
    await redis.aclose()

    assert upserted == [vehicle["vehicle_id"]]
