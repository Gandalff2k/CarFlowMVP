"""create roles, users and idempotency_keys tables

Revision ID: 0001
Revises:
Create Date: 2026-08-29

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
        "roles",
        sa.Column("code", sa.String(length=16), primary_key=True),
    )
    op.bulk_insert(
        sa.table("roles", sa.column("code", sa.String)),
        [{"code": "renter"}, {"code": "host"}, {"code": "admin"}],
    )
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False, unique=True),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("password_hash", sa.String(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=16),
            sa.ForeignKey("roles.code"),
            nullable=False,
            server_default="renter",
        ),
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
    op.drop_table("users")
    op.drop_table("roles")
