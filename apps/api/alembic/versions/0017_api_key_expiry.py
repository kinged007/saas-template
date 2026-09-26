"""api key expiry

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
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("api_keys")}
    if "expires_at" not in cols:
        op.add_column(
            "api_keys",
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
    # Indexed for the apikeys.cleanup scan and the list view's expires_at sort.
    idx = {i["name"] for i in sa.inspect(bind).get_indexes("api_keys")}
    if "ix_api_keys_expires_at" not in idx:
        op.create_index("ix_api_keys_expires_at", "api_keys", ["expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("api_keys")}
    if "expires_at" in cols:
        idx = {i["name"] for i in sa.inspect(bind).get_indexes("api_keys")}
        if "ix_api_keys_expires_at" in idx:
            op.drop_index("ix_api_keys_expires_at", table_name="api_keys")
        op.drop_column("api_keys", "expires_at")
