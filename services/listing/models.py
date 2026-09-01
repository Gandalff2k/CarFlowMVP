import datetime as dt
import uuid

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # host_id is a claim from the auth-issued JWT, not a foreign key
    host_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    make: Mapped[str] = mapped_column(String(80), nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    year: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_price_cents: Mapped[int] = mapped_column(Integer, nullable=False)
    daily_mileage_limit: Mapped[int] = mapped_column(Integer, nullable=False)
    booking_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="instant")
    approval_status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: dt.datetime.now(dt.UTC),
        onupdate=lambda: dt.datetime.now(dt.UTC),
    )


class AvailabilityBlock(Base):
    __tablename__ = "availability_blocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    vehicle_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicles.id"), nullable=False
    )
    start_date: Mapped[dt.date] = mapped_column(nullable=False)
    end_date: Mapped[dt.date] = mapped_column(nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: dt.datetime.now(dt.UTC)
    )
