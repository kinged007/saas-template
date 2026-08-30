"""workspace_settings

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("workspace_settings"):
        return
    dialect = bind.dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

    op.create_table(
        "workspace_settings",
        sa.Column("id", ID, primary_key=True),
        sa.Column("workspace_id", ID, nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("updated_by_user_id", ID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", "key", name="uq_workspace_settings_workspace_key"),
    )
    op.create_index("ix_workspace_settings_workspace_id", "workspace_settings", ["workspace_id"])
    op.create_index("ix_workspace_settings_updated_by_user_id", "workspace_settings", ["updated_by_user_id"])


def downgrade() -> None:
    op.drop_table("workspace_settings")
