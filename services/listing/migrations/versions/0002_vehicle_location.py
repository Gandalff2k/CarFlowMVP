"""add latitude/longitude to vehicles

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-02

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # NOT NULL with no server_default: safe because nothing has ever written
    # to this table outside ephemeral local/test Postgres instances (no
    # persistent volume in docker-compose), so there is no existing data to
    # backfill.
    op.add_column("vehicles", sa.Column("latitude", sa.Float(), nullable=False))
    op.add_column("vehicles", sa.Column("longitude", sa.Float(), nullable=False))


def downgrade() -> None:
    op.drop_column("vehicles", "longitude")
    op.drop_column("vehicles", "latitude")
