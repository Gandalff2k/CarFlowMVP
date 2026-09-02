import datetime as dt
import uuid

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Booking(Base):
    """The read-model projection: current state of one booking.

    `payment_authorized` never appears as a resting value here — it settles
    straight through to `confirmed` because nothing external happens in
    between (see services/booking/domain.py:confirm_after_payment_authorized).
    The full causal history, including that intermediate event, lives in
    BookingEvent.
    """

    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    renter_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    start_date: Mapped[dt.date] = mapped_column(nullable=False)
    end_date: Mapped[dt.date] = mapped_column(nullable=False)
    daily_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_mileage_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    booking_mode: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="requested")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    start_odometer: Mapped[int | None] = mapped_column(Integer)
    end_odometer: Mapped[int | None] = mapped_column(Integer)
    start_fuel_percent: Mapped[int | None] = mapped_column(Integer)
    end_fuel_percent: Mapped[int | None] = mapped_column(Integer)
    start_photo_url: Mapped[str | None] = mapped_column(String(512))
    end_photo_url: Mapped[str | None] = mapped_column(String(512))
    overage_cents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class BookingEvent(Base):
    """Append-only event store. UNIQUE(booking_id, version) is the optimistic
    concurrency check: appending version N twice for the same booking can
    only ever succeed once."""

    __tablename__ = "booking_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    booking_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
