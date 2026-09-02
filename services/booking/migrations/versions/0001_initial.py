"""create bookings, booking_events, outbox, inbox and idempotency_keys tables

Revision ID: 0001
Revises:
Create Date: 2026-09-01

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Needed for the EXCLUDE USING gist constraint below (see services/listing's
    # 0001 migration for the same reasoning: it adds the `=` operator class for
    # uuid so it can combine with daterange's `&&` in one GiST index).
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "bookings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("vehicle_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("renter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("daily_price_cents", sa.Integer(), nullable=False),
        sa.Column("daily_mileage_limit", sa.Integer(), nullable=False),
        sa.Column("booking_mode", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="requested"),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("start_odometer", sa.Integer(), nullable=True),
        sa.Column("end_odometer", sa.Integer(), nullable=True),
        sa.Column("start_fuel_percent", sa.Integer(), nullable=True),
        sa.Column("end_fuel_percent", sa.Integer(), nullable=True),
        sa.Column("start_photo_url", sa.String(length=512), nullable=True),
        sa.Column("end_photo_url", sa.String(length=512), nullable=True),
        sa.Column("overage_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('requested', 'confirmed', 'active', 'completed', 'cancelled', 'rejected')",
            name="ck_bookings_status",
        ),
    )
    # The double-booking guard: two overlapping date ranges for the same
    # vehicle can never both hold a non-terminal booking. This fires at
    # INSERT time of the request itself, so it is the actual reservation,
    # not just documentation of intent.
    op.execute(
        "ALTER TABLE bookings ADD CONSTRAINT ex_bookings_no_overlap "
        "EXCLUDE USING gist (vehicle_id WITH =, daterange(start_date, end_date, '[]') WITH &&) "
        "WHERE (status NOT IN ('cancelled', 'rejected'))"
    )

    op.create_table(
        "booking_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("booking_id", "version", name="uq_booking_events_booking_version"),
    )

    # Column names match Debezium's outbox EventRouter SMT defaults exactly
    # (see services/listing/outbox.py and infra/debezium/*-connector.json).
    op.create_table(
        "outbox",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("aggregatetype", sa.String(length=255), nullable=False),
        sa.Column("aggregateid", sa.String(length=255), nullable=False),
        sa.Column("type", sa.String(length=255), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "inbox",
        sa.Column("event_id", sa.Text(), primary_key=True),
        sa.Column(
            "processed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "idempotency_keys",
        sa.Column("consumer_id", sa.Text(), nullable=False, server_default=""),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("request_hash", sa.Text(), nullable=False),
        sa.Column("response_body", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.PrimaryKeyConstraint("consumer_id", "key"),
    )


def downgrade() -> None:
    op.drop_table("idempotency_keys")
    op.drop_table("inbox")
    op.drop_table("outbox")
    op.drop_table("booking_events")
    op.drop_table("bookings")
