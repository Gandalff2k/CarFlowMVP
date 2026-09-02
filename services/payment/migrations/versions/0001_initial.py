"""create payments, ledger_entries, outbox and inbox tables

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
    op.create_table(
        "payments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True),
        sa.Column("renter_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("hold_amount_cents", sa.Integer(), nullable=False),
        sa.Column("overage_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("stripe_payment_intent_id", sa.String(length=255), nullable=True),
        sa.Column("stripe_overage_intent_id", sa.String(length=255), nullable=True),
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
            "status IN ('authorized', 'authorization_failed', 'captured', 'capture_failed')",
            name="ck_payments_status",
        ),
    )

    op.create_table(
        "ledger_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "payment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("payments.id"),
            nullable=False,
        ),
        sa.Column("booking_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account", sa.String(length=64), nullable=False),
        sa.Column("direction", sa.String(length=6), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("direction IN ('debit', 'credit')", name="ck_ledger_entries_direction"),
        sa.CheckConstraint("amount_cents > 0", name="ck_ledger_entries_amount_positive"),
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

    # Doubles as dedup storage for both the Kafka consumer (booking commands)
    # and the Stripe webhook (keyed by Stripe's own event id) - same
    # "claim before acting" mechanism, two different event sources.
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


def downgrade() -> None:
    op.drop_table("inbox")
    op.drop_table("outbox")
    op.drop_table("ledger_entries")
    op.drop_table("payments")
