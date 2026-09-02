import json
from typing import Any

from aiokafka import AIOKafkaConsumer
from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis

from services.telemetry.repository import write_batch, write_latest_position
from shared.kafka_consumer import report_consumer_lag


def build_batch(raw_records: list[bytes]) -> tuple[list[dict], dict[str, dict]]:
    """Pure: decode a batch of raw Kafka values into Mongo-ready documents
    plus the last-seen packet per vehicle (last one wins, in arrival order —
    good enough for a "where is it now" read, no ordering guarantees needed
    beyond that)."""
    documents: list[dict] = []
    latest_by_vehicle: dict[str, dict] = {}
    for raw in raw_records:
        packet = json.loads(raw)
        documents.append(packet)
        latest_by_vehicle[packet["vehicle_id"]] = packet
    return documents, latest_by_vehicle


async def run_telemetry_consumer(
    *,
    bootstrap_servers: str,
    topic: str,
    group_id: str,
    mongo_db: AsyncIOMotorDatabase,
    redis: Redis,
    redis_ttl_seconds: int,
    batch_size: int,
    batch_interval_seconds: float,
    service_name: str = "telemetry",
) -> None:
    consumer = AIOKafkaConsumer(
        topic,
        bootstrap_servers=bootstrap_servers,
        group_id=group_id,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    try:
        while True:
            batches: dict[Any, list] = await consumer.getmany(
                timeout_ms=int(batch_interval_seconds * 1000), max_records=batch_size
            )
            raw_records = [record.value for records in batches.values() for record in records]
            if not raw_records:
                continue
            documents, latest_by_vehicle = build_batch(raw_records)
            await write_batch(mongo_db, documents)
            for vehicle_id, packet in latest_by_vehicle.items():
                await write_latest_position(
                    redis,
                    vehicle_id=vehicle_id,
                    lat=packet["lat"],
                    lng=packet["lng"],
                    recorded_at=packet["recorded_at"],
                    ttl_seconds=redis_ttl_seconds,
                )
            await consumer.commit()
            await report_consumer_lag(consumer, service=service_name, topic=topic)
    finally:
        await consumer.stop()
