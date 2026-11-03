"""workspace mfa_required flag

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("workspaces")}
    if "mfa_required" not in cols:
        op.add_column(
            "workspaces",
            sa.Column("mfa_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("workspaces")}
    if "mfa_required" in cols:
        op.drop_column("workspaces", "mfa_required")
