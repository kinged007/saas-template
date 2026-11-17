"""api key quota window: per-calendar-month counter

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-26 00:00:00.000000
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # usage_count stays the lifetime total; usage_window_count is the counter
    # usage_quota caps, reset when a request lands in a later calendar month.
    op.add_column(
        "api_keys",
        sa.Column("usage_window_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "api_keys", sa.Column("usage_window_start", sa.DateTime(timezone=True), nullable=True)
    )
    # Seed the window from the lifetime total so the deploy does not hand a
    # second full budget to a key that had already exhausted its old lifetime
    # quota: such a key stays rejected until the next month boundary, and from
    # that boundary on it gets a fresh budget every month.
    #
    # usage_window_start is seeded too, and that half is not optional: a NULL
    # start reads as "no window has been opened yet", so the rollover zeroes
    # the counter on the key's first request and the seed above is discarded.
    #
    # Capped keys only. An unlimited key had no cap to exhaust, so seeding it
    # buys nothing and puts its lifetime total in the new "Usage (this month)"
    # column until the month rolls; it keeps an empty window and record_use
    # opens one on its first use.
    #
    # op.execute() takes no bound parameters (the bind connection does), and
    # the typed bindparam is what lets sqlite3 bind a datetime at all.
    month_start = datetime.now(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    op.get_bind().execute(
        sa.text(
            "UPDATE api_keys SET usage_window_count = usage_count, usage_window_start = :start"
            " WHERE usage_quota IS NOT NULL"
        ).bindparams(sa.bindparam("start", type_=sa.DateTime(timezone=True))),
        {"start": month_start},
    )


def downgrade() -> None:
    op.drop_column("api_keys", "usage_window_start")
    op.drop_column("api_keys", "usage_window_count")
