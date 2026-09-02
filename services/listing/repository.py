import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.listing.models import AvailabilityBlock, Vehicle


class OverlappingAvailabilityBlockError(Exception):
    pass


class VehicleRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, vehicle_id: uuid.UUID) -> Vehicle | None:
        result = await self._session.execute(select(Vehicle).where(Vehicle.id == vehicle_id))
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        host_id: uuid.UUID,
        make: str,
        model: str,
        year: int,
        daily_price_cents: int,
        daily_mileage_limit: int,
        booking_mode: str,
        latitude: float,
        longitude: float,
    ) -> Vehicle:
        vehicle = Vehicle(
            host_id=host_id,
            make=make,
            model=model,
            year=year,
            daily_price_cents=daily_price_cents,
            daily_mileage_limit=daily_mileage_limit,
            booking_mode=booking_mode,
            latitude=latitude,
            longitude=longitude,
        )
        self._session.add(vehicle)
        await self._session.flush()
        return vehicle

    async def save(self, vehicle: Vehicle) -> None:
        await self._session.flush()

    async def list_by_approval_status(
        self, *, approval_status: str, limit: int, offset: int
    ) -> list[Vehicle]:
        result = await self._session.execute(
            select(Vehicle)
            .where(Vehicle.approval_status == approval_status)
            .order_by(Vehicle.created_at, Vehicle.id)
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())


class AvailabilityBlockRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(self, *, vehicle_id: uuid.UUID, start_date, end_date) -> AvailabilityBlock:
        block = AvailabilityBlock(vehicle_id=vehicle_id, start_date=start_date, end_date=end_date)
        self._session.add(block)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise OverlappingAvailabilityBlockError(vehicle_id) from exc
        return block
