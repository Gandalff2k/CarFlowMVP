"""create vehicles, availability_blocks, outbox and idempotency_keys tables

Revision ID: 0001
Revises:
Create Date: 2026-08-30

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
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    op.create_table(
        "vehicles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("host_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("make", sa.String(length=80), nullable=False),
        sa.Column("model", sa.String(length=80), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("daily_price_cents", sa.Integer(), nullable=False),
        sa.Column("daily_mileage_limit", sa.Integer(), nullable=False),
        sa.Column("booking_mode", sa.String(length=16), nullable=False, server_default="instant"),
        sa.Column(
            "approval_status", sa.String(length=16), nullable=False, server_default="pending"
        ),
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
            "booking_mode IN ('instant', 'request')", name="ck_vehicles_booking_mode"
        ),
        sa.CheckConstraint(
            "approval_status IN ('pending', 'approved', 'rejected')",
            name="ck_vehicles_approval_status",
        ),
    )

    op.create_table(
        "availability_blocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "vehicle_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("vehicles.id"),
            nullable=False,
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("end_date >= start_date", name="ck_availability_blocks_date_order"),
    )
    op.execute(
        "ALTER TABLE availability_blocks ADD CONSTRAINT ex_availability_blocks_overlap "
        "EXCLUDE USING gist (vehicle_id WITH =, daterange(start_date, end_date, '[]') WITH &&)"
    )

    # Column names match Debezium's outbox EventRouter SMT defaults exactly
    # (see services/listing/outbox.py and infra/debezium/listing-outbox-connector.json).
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
    op.drop_table("outbox")
    op.drop_table("availability_blocks")
    op.drop_table("vehicles")
