import json

from motor.motor_asyncio import AsyncIOMotorDatabase
from redis.asyncio import Redis


async def write_batch(mongo_db: AsyncIOMotorDatabase, documents: list[dict]) -> None:
    if documents:
        await mongo_db.packets.insert_many(documents)


async def write_latest_position(
    redis: Redis, *, vehicle_id: str, lat: float, lng: float, recorded_at: str, ttl_seconds: int
) -> None:
    await redis.set(
        f"vehicle-location:{vehicle_id}",
        json.dumps({"lat": lat, "lng": lng, "recorded_at": recorded_at}),
        ex=ttl_seconds,
    )


async def get_latest_position(redis: Redis, *, vehicle_id: str) -> dict | None:
    raw = await redis.get(f"vehicle-location:{vehicle_id}")
    return json.loads(raw) if raw is not None else None
