"""api key usage counting + per-key quota

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-19 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "api_keys", sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column("api_keys", sa.Column("usage_quota", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("api_keys", "usage_quota")
    op.drop_column("api_keys", "usage_count")
