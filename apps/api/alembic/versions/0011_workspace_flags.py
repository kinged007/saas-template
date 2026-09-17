"""workspace feature flags (JSON column on workspaces)

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("workspaces", sa.Column("flags", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    op.drop_column("workspaces", "flags")
