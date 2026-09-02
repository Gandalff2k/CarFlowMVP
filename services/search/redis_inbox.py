from redis.asyncio import Redis

# Unlike booking/payment's Postgres inbox, this dedup key expires (TTL) rather
# than being purged by a separate cleanup loop, and it is NOT applied in the
# same transaction as the effect it guards — there is no cross-system
# transaction spanning Redis and Elasticsearch. That's fine here because the
# effect (an ES upsert/delete by vehicle_id) is naturally idempotent: applying
# it twice leaves the same document, unlike Stripe's "authorize a payment",
# which is not. Weaker dedup is an intentional match to weaker risk.


async def claim_event(redis: Redis, *, event_id: str, ttl_seconds: int) -> bool:
    claimed = await redis.set(f"processed-event:{event_id}", "1", nx=True, ex=ttl_seconds)
    return bool(claimed)
