"""Bulk-index existing approved vehicles from listing into the search index.

One-off operational tool, run manually or from a job:
    docker compose run --rm search python -m services.search.backfill

Mints its own short-lived admin-role JWT using the shared JWT secret rather
than calling through Kong with a real admin's token — there is no human
operator in the loop for a backfill run, so this script IS the trusted
caller, the same way Debezium's own connector user is trusted infrastructure
rather than an end-user account.
"""

import asyncio
import uuid

import httpx

from services.auth.security import create_token
from services.search.config import SearchSettings
from services.search.es_client import create_es_client, ensure_index
from services.search.repository import SearchRepository
from services.search.service import handle_vehicle_event

PAGE_SIZE = 100


def _event_data(vehicle: dict) -> dict:
    return {
        "vehicle_id": vehicle["id"],
        "host_id": vehicle["host_id"],
        "make": vehicle["make"],
        "model": vehicle["model"],
        "year": vehicle["year"],
        "daily_price_cents": vehicle["daily_price_cents"],
        "daily_mileage_limit": vehicle["daily_mileage_limit"],
        "booking_mode": vehicle["booking_mode"],
        "approval_status": vehicle["approval_status"],
        "latitude": vehicle["latitude"],
        "longitude": vehicle["longitude"],
    }


async def run_backfill(settings: SearchSettings) -> int:
    es = create_es_client(settings.elasticsearch_url)
    await ensure_index(es, settings.index_name)
    repo = SearchRepository(es, settings.index_name)

    token = create_token(
        user_id=uuid.uuid4(),
        role="admin",
        token_type="access",
        secret=settings.jwt_secret,
        issuer=settings.jwt_issuer,
        ttl_seconds=300,
    )
    headers = {"Authorization": f"Bearer {token}"}

    indexed = 0
    try:
        async with httpx.AsyncClient(base_url=settings.listing_base_url) as client:
            offset = 0
            while True:
                response = await client.get(
                    "/listing/vehicles",
                    params={"approval_status": "approved", "limit": PAGE_SIZE, "offset": offset},
                    headers=headers,
                )
                response.raise_for_status()
                body = response.json()
                for vehicle in body["items"]:
                    await handle_vehicle_event(repo, data=_event_data(vehicle))
                    indexed += 1
                if body["next_offset"] is None:
                    break
                offset = body["next_offset"]
    finally:
        await es.close()
    return indexed


async def main() -> None:
    count = await run_backfill(SearchSettings())
    print(f"Backfilled {count} approved vehicle(s) into the search index.")


if __name__ == "__main__":
    asyncio.run(main())
