"""agents

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-30 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agents"):
        return
    dialect = bind.dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

    def _id(name: str = "id") -> sa.Column:
        return sa.Column(name, ID, primary_key=True)

    op.create_table(
        "agents",
        sa.Column("id", ID, primary_key=True),
        sa.Column("workspace_id", ID, nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("avatar", sa.String(length=300), nullable=True),
        sa.Column("system_prompt", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("temperature", sa.Float(), nullable=True),
        sa.Column("max_tokens", sa.Integer(), nullable=True),
        sa.Column("tool_allowlist", sa.JSON(), nullable=True),
        sa.Column("mcp_servers", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("execution_target", sa.String(length=30), nullable=True),
        sa.Column("role_id", ID, nullable=True),
        sa.Column("skills", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("custom_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_by_user_id", ID, nullable=True),
        sa.Column("updated_by_user_id", ID, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("workspace_id", "slug", name="uq_agents_workspace_slug"),
    )
    op.create_index("ix_agents_workspace_id", "agents", ["workspace_id"])
    op.create_index("ix_agents_role_id", "agents", ["role_id"])
    op.create_index("ix_agents_created_by_user_id", "agents", ["created_by_user_id"])
    op.create_index("ix_agents_updated_by_user_id", "agents", ["updated_by_user_id"])


def downgrade() -> None:
    op.drop_table("agents")
