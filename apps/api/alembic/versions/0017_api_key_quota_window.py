"""api key quota window: per-calendar-month counter

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # usage_count stays the lifetime total; usage_window_count is the counter
    # usage_quota caps, reset when a request lands in a later calendar month.
    # New keys start the window empty: usage_window_start is set on first use.
    op.add_column(
        "api_keys",
        sa.Column("usage_window_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "api_keys", sa.Column("usage_window_start", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("api_keys", "usage_window_start")
    op.drop_column("api_keys", "usage_window_count")
