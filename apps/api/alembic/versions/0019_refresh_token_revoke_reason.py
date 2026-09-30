"""refresh token revoke reason

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("refresh_tokens")}
    if "revoke_reason" not in cols:
        op.add_column(
            "refresh_tokens",
            sa.Column("revoke_reason", sa.String(20), nullable=True),
        )
        # Existing rows carry a revoked_at but no reason, so they read as
        # "revoked by unknown means" and never arm the reuse signal.
        op.execute(
            "UPDATE refresh_tokens SET revoke_reason = 'user' "
            "WHERE revoked_at IS NOT NULL AND revoke_reason IS NULL"
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("refresh_tokens")}
    if "revoke_reason" in cols:
        op.drop_column("refresh_tokens", "revoke_reason")
