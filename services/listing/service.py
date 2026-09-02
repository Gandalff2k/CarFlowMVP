import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from services.listing.models import Vehicle
from services.listing.repository import AvailabilityBlockRepository, VehicleRepository
from shared.outbox import write_outbox_event

MUTABLE_VEHICLE_FIELDS = (
    "make",
    "model",
    "year",
    "daily_price_cents",
    "daily_mileage_limit",
    "booking_mode",
)


class VehicleNotFoundError(Exception):
    pass


class NotVehicleOwnerError(Exception):
    pass


class InvalidApprovalTransitionError(Exception):
    pass


async def create_vehicle(
    repo: VehicleRepository,
    *,
    host_id: uuid.UUID,
    make: str,
    model: str,
    year: int,
    daily_price_cents: int,
    daily_mileage_limit: int,
    booking_mode: str,
) -> Vehicle:
    return await repo.create(
        host_id=host_id,
        make=make,
        model=model,
        year=year,
        daily_price_cents=daily_price_cents,
        daily_mileage_limit=daily_mileage_limit,
        booking_mode=booking_mode,
    )


async def get_owned_vehicle(
    repo: VehicleRepository, *, vehicle_id: uuid.UUID, host_id: uuid.UUID
) -> Vehicle:
    vehicle = await repo.get_by_id(vehicle_id)
    if vehicle is None:
        raise VehicleNotFoundError(vehicle_id)
    if vehicle.host_id != host_id:
        raise NotVehicleOwnerError(vehicle_id)
    return vehicle


async def get_vehicle_for_viewer(
    repo: VehicleRepository, *, vehicle_id: uuid.UUID, viewer_id: uuid.UUID, viewer_role: str
) -> Vehicle:
    vehicle = await repo.get_by_id(vehicle_id)
    if vehicle is None:
        raise VehicleNotFoundError(vehicle_id)
    is_owner_or_admin = viewer_role == "admin" or vehicle.host_id == viewer_id
    if not is_owner_or_admin and vehicle.approval_status != "approved":
        raise NotVehicleOwnerError(vehicle_id)
    return vehicle


async def update_vehicle(
    repo: VehicleRepository,
    session: AsyncSession,
    *,
    vehicle_id: uuid.UUID,
    host_id: uuid.UUID,
    **fields: object,
) -> Vehicle:
    vehicle = await get_owned_vehicle(repo, vehicle_id=vehicle_id, host_id=host_id)
    for field in MUTABLE_VEHICLE_FIELDS:
        value = fields.get(field)
        if value is not None:
            setattr(vehicle, field, value)
    await repo.save(vehicle)
    await write_outbox_event(
        session,
        aggregate_type="vehicle",
        aggregate_id=str(vehicle.id),
        event_type="vehicle_updated",
        data={"vehicle_id": str(vehicle.id)},
    )
    return vehicle


async def approve_vehicle(
    repo: VehicleRepository, session: AsyncSession, *, vehicle_id: uuid.UUID
) -> Vehicle:
    vehicle = await repo.get_by_id(vehicle_id)
    if vehicle is None:
        raise VehicleNotFoundError(vehicle_id)
    if vehicle.approval_status != "pending":
        raise InvalidApprovalTransitionError(vehicle.approval_status)
    vehicle.approval_status = "approved"
    await repo.save(vehicle)
    await write_outbox_event(
        session,
        aggregate_type="vehicle",
        aggregate_id=str(vehicle.id),
        event_type="vehicle_approved",
        data={"vehicle_id": str(vehicle.id)},
    )
    return vehicle


async def reject_vehicle(repo: VehicleRepository, *, vehicle_id: uuid.UUID) -> Vehicle:
    vehicle = await repo.get_by_id(vehicle_id)
    if vehicle is None:
        raise VehicleNotFoundError(vehicle_id)
    if vehicle.approval_status != "pending":
        raise InvalidApprovalTransitionError(vehicle.approval_status)
    vehicle.approval_status = "rejected"
    await repo.save(vehicle)
    return vehicle


async def add_availability_block(
    availability_repo: AvailabilityBlockRepository,
    vehicle_repo: VehicleRepository,
    *,
    vehicle_id: uuid.UUID,
    host_id: uuid.UUID,
    start_date,
    end_date,
):
    await get_owned_vehicle(vehicle_repo, vehicle_id=vehicle_id, host_id=host_id)
    return await availability_repo.create(
        vehicle_id=vehicle_id, start_date=start_date, end_date=end_date
    )
