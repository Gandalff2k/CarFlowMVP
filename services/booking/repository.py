import datetime as dt
import uuid

from sqlalchemy import insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from services.booking.domain import BookingState
from services.booking.models import Booking, BookingEvent


class OverlappingBookingError(Exception):
    pass


class ConcurrentBookingUpdateError(Exception):
    pass


def _to_state(row: Booking) -> BookingState:
    return BookingState(
        id=row.id,
        vehicle_id=row.vehicle_id,
        host_id=row.host_id,
        renter_id=row.renter_id,
        start_date=row.start_date,
        end_date=row.end_date,
        daily_price_cents=row.daily_price_cents,
        daily_mileage_limit=row.daily_mileage_limit,
        booking_mode=row.booking_mode,
        status=row.status,
        version=row.version,
        start_odometer=row.start_odometer,
        end_odometer=row.end_odometer,
        start_fuel_percent=row.start_fuel_percent,
        end_fuel_percent=row.end_fuel_percent,
        start_photo_url=row.start_photo_url,
        end_photo_url=row.end_photo_url,
        overage_cents=row.overage_cents,
    )


class BookingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, booking_id: uuid.UUID) -> Booking | None:
        result = await self._session.execute(select(Booking).where(Booking.id == booking_id))
        return result.scalar_one_or_none()

    async def create_requested(
        self,
        *,
        vehicle_id: uuid.UUID,
        host_id: uuid.UUID,
        renter_id: uuid.UUID,
        start_date: dt.date,
        end_date: dt.date,
        daily_price_cents: int,
        daily_mileage_limit: int,
        booking_mode: str,
    ) -> Booking:
        booking = Booking(
            id=uuid.uuid4(),
            vehicle_id=vehicle_id,
            host_id=host_id,
            renter_id=renter_id,
            start_date=start_date,
            end_date=end_date,
            daily_price_cents=daily_price_cents,
            daily_mileage_limit=daily_mileage_limit,
            booking_mode=booking_mode,
            status="requested",
            version=1,
        )
        self._session.add(booking)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise OverlappingBookingError(vehicle_id) from exc
        return booking

    async def append_events(
        self, *, booking: Booking, events: list[tuple[str, dict]], next_status: str
    ) -> None:
        for offset, (event_type, payload) in enumerate(events, start=1):
            next_version = booking.version + offset
            try:
                await self._session.execute(
                    insert(BookingEvent).values(
                        id=uuid.uuid4(),
                        booking_id=booking.id,
                        version=next_version,
                        event_type=event_type,
                        payload=payload,
                    )
                )
                await self._session.flush()
            except IntegrityError as exc:
                raise ConcurrentBookingUpdateError(booking.id) from exc
        booking.version += len(events)
        booking.status = next_status

    async def save(self, booking: Booking) -> None:
        await self._session.flush()

    def state_of(self, booking: Booking) -> BookingState:
        return _to_state(booking)

    async def list_all(self, *, limit: int, offset: int) -> list[Booking]:
        result = await self._session.execute(
            select(Booking).order_by(Booking.created_at, Booking.id).limit(limit).offset(offset)
        )
        return list(result.scalars().all())
