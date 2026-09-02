from typing import Any

from redis.asyncio import Redis

from services.search.redis_inbox import claim_event
from services.search.repository import SearchRepository
from services.search.service import handle_vehicle_event
from shared.kafka_consumer import EventProcessor

LISTING_EVENT_TYPES = ("vehicle_approved", "vehicle_updated")


def build_listing_event_processor(
    redis: Redis, repo: SearchRepository, *, dedup_ttl_seconds: int = 86400
) -> EventProcessor:
    async def process(event_id: str, event_type: str, data: dict[str, Any]) -> None:
        if event_type not in LISTING_EVENT_TYPES:
            return
        if not await claim_event(redis, event_id=event_id, ttl_seconds=dedup_ttl_seconds):
            return
        await handle_vehicle_event(repo, data=data)

    return process
