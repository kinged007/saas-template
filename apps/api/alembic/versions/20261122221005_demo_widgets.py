"""demo widgets (project extension seam #1794)

Revision ID: 20261122221005
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "20261122221005"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)
    op.create_table(
        "demo_widgets",
        sa.Column("id", ID, primary_key=True),
        sa.Column("workspace_id", ID, nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index(op.f("ix_demo_widgets_workspace_id"), "demo_widgets", ["workspace_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_demo_widgets_workspace_id"), table_name="demo_widgets")
    op.drop_table("demo_widgets")
