"""rename workspace mfa_required to require_mfa (staging parity)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspaces"


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if "require_mfa" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("require_mfa", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "mfa_required" in cols:
        op.execute(f"UPDATE {_TABLE} SET require_mfa = mfa_required")
        op.drop_column(_TABLE, "mfa_required")


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if "mfa_required" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("mfa_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "require_mfa" in cols:
        op.execute(f"UPDATE {_TABLE} SET mfa_required = require_mfa")
        op.drop_column(_TABLE, "require_mfa")
