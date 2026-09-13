"""stored_secrets expires_at

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-12 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("stored_secrets")}
    if "expires_at" not in cols:
        op.add_column(
            "stored_secrets",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )

def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("stored_secrets")}
    if "expires_at" in cols:
        op.drop_column("stored_secrets", "expires_at")
