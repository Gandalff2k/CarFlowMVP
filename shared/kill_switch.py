from redis.asyncio import Redis

# Shared between admin (writer) and telemetry (reader) 

_KEY_PREFIX = "kill-switch"


def _key(vehicle_id: str) -> str:
    return f"{_KEY_PREFIX}:{vehicle_id}"


async def activate(redis: Redis, *, vehicle_id: str) -> None:
    await redis.set(_key(vehicle_id), "1")


async def deactivate(redis: Redis, *, vehicle_id: str) -> None:
    await redis.delete(_key(vehicle_id))


async def is_active(redis: Redis, *, vehicle_id: str) -> bool:
    return bool(await redis.exists(_key(vehicle_id)))
