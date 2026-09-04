"""agent_usage

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-04 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_usage"):
        return
    dialect = bind.dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    op.create_table(
        "agent_usage",
        sa.Column("id", ID, primary_key=True),
        sa.Column("workspace_id", ID, nullable=False),
        sa.Column("agent_id", ID, nullable=False),
        sa.Column("user_id", ID, nullable=True),
        sa.Column("conversation_id", ID, nullable=True),
        sa.Column("message_id", ID, nullable=True),
        sa.Column("model", sa.String(length=100), nullable=False, server_default=""),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_cents", sa.Numeric(10, 4), nullable=False, server_default="0"),
        sa.Column("latency_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tool_calls_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="success"),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index(
        "ix_agent_usage_workspace_created", "agent_usage", ["workspace_id", "created_at"]
    )
    op.create_index(
        "ix_agent_usage_agent_created", "agent_usage", ["agent_id", "created_at"]
    )
    op.create_index("ix_agent_usage_user", "agent_usage", ["user_id"])
    op.create_index("ix_agent_usage_status", "agent_usage", ["status"])


def downgrade() -> None:
    for name in [
        "ix_agent_usage_status",
        "ix_agent_usage_user",
        "ix_agent_usage_agent_created",
        "ix_agent_usage_workspace_created",
    ]:
        try:
            op.drop_index(name, table_name="agent_usage")
        except Exception:
            pass
    op.drop_table("agent_usage")