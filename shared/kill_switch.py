from redis.asyncio import Redis

# Shared between admin (writer) and telemetry (reader) — a real, if minimal,
# safety mechanism rather than a decorative stub: admin records *intent* in
# its own audit log (services/admin/models.py:AdminAction) regardless, but
# this flag is what telemetry actually checks and enforces server-side
# (services/telemetry/app.py forces speed_kph=0 while it's set), since a
# real device cannot be trusted to obey a remote command on its own.

_KEY_PREFIX = "kill-switch"


def _key(vehicle_id: str) -> str:
    return f"{_KEY_PREFIX}:{vehicle_id}"


async def activate(redis: Redis, *, vehicle_id: str) -> None:
    await redis.set(_key(vehicle_id), "1")


async def deactivate(redis: Redis, *, vehicle_id: str) -> None:
    await redis.delete(_key(vehicle_id))


async def is_active(redis: Redis, *, vehicle_id: str) -> bool:
    return bool(await redis.exists(_key(vehicle_id)))
