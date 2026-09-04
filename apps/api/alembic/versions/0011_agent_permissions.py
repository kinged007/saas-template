"""agent_permission_requests

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-03 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_permission_requests"):
        return
    dialect = bind.dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

    op.create_table(
        "agent_permission_requests",
        sa.Column("id", ID, primary_key=True),
        sa.Column("workspace_id", ID, nullable=False),
        sa.Column("conversation_id", ID, nullable=False),
        sa.Column("agent_id", ID, nullable=False),
        sa.Column("triggering_user_id", ID, nullable=False),
        sa.Column("run_message_id", ID, nullable=True),
        sa.Column("tool_name", sa.String(length=200), nullable=False),
        sa.Column("tool_call_id", sa.String(length=100), nullable=False),
        sa.Column("args_summary", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("decision_note", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", ID, nullable=True),
        _ts("created_at"),
        sa.Column("decided_at", TS, nullable=True),
        sa.Column("expires_at", TS, nullable=False),
    )
    op.create_index("ix_agent_perm_req_workspace", "agent_permission_requests", ["workspace_id"])
    op.create_index("ix_agent_perm_req_conv", "agent_permission_requests", ["conversation_id"])
    op.create_index("ix_agent_perm_req_agent", "agent_permission_requests", ["agent_id"])
    op.create_index("ix_agent_perm_req_status", "agent_permission_requests", ["status"])


def downgrade() -> None:
    for name in [
        "ix_agent_perm_req_status",
        "ix_agent_perm_req_agent",
        "ix_agent_perm_req_conv",
        "ix_agent_perm_req_workspace",
    ]:
        try:
            op.drop_index(name, table_name="agent_permission_requests")
        except Exception:
            pass
    op.drop_table("agent_permission_requests")
