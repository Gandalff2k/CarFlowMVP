import uuid

from redis.asyncio import Redis

from services.admin.clients import BookingClient, ListingClient
from services.admin.repository import AdminActionRepository
from shared import kill_switch


async def approve_vehicle(
    listing_client: ListingClient,
    actions_repo: AdminActionRepository,
    *,
    admin_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    bearer_token: str,
) -> dict:
    vehicle = await listing_client.approve_vehicle(vehicle_id, bearer_token=bearer_token)
    await actions_repo.record(
        admin_id=admin_id,
        action_type="vehicle_approved",
        target_type="vehicle",
        target_id=str(vehicle_id),
    )
    return vehicle


async def reject_vehicle(
    listing_client: ListingClient,
    actions_repo: AdminActionRepository,
    *,
    admin_id: uuid.UUID,
    vehicle_id: uuid.UUID,
    bearer_token: str,
) -> dict:
    vehicle = await listing_client.reject_vehicle(vehicle_id, bearer_token=bearer_token)
    await actions_repo.record(
        admin_id=admin_id,
        action_type="vehicle_rejected",
        target_type="vehicle",
        target_id=str(vehicle_id),
    )
    return vehicle


async def list_bookings(
    booking_client: BookingClient, *, bearer_token: str, limit: int, offset: int
) -> dict:
    return await booking_client.list_bookings(bearer_token=bearer_token, limit=limit, offset=offset)


async def activate_kill_switch(
    redis: Redis,
    actions_repo: AdminActionRepository,
    *,
    admin_id: uuid.UUID,
    vehicle_id: uuid.UUID,
) -> None:
    await kill_switch.activate(redis, vehicle_id=str(vehicle_id))
    await actions_repo.record(
        admin_id=admin_id,
        action_type="kill_switch_activated",
        target_type="vehicle",
        target_id=str(vehicle_id),
    )


async def deactivate_kill_switch(
    redis: Redis,
    actions_repo: AdminActionRepository,
    *,
    admin_id: uuid.UUID,
    vehicle_id: uuid.UUID,
) -> None:
    await kill_switch.deactivate(redis, vehicle_id=str(vehicle_id))
    await actions_repo.record(
        admin_id=admin_id,
        action_type="kill_switch_deactivated",
        target_type="vehicle",
        target_id=str(vehicle_id),
    )
