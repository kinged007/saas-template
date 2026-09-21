"""record session client metadata (ip + user agent)

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.add_column(
        "refresh_tokens", sa.Column("user_agent", sa.String(length=500), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_column("refresh_tokens", "ip_address")
