"""agent_memories

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("agent_memories"):
        return
    dialect = bind.dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    # pgvector vector(1536) on Postgres when the extension is available; the
    # column is nullable and only written when settings.vector_enabled, so the
    # schema works (and migrations run) without pgvector in dev.
    EMBEDDING = sa.Text()
    if dialect == "postgresql":
        try:
            from pgvector.sqlalchemy import Vector

            EMBEDDING = Vector(1536)
        except ImportError:
            pass

    def _ts(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

    op.create_table(
        "agent_memories",
        sa.Column("id", ID, primary_key=True),
        sa.Column("workspace_id", ID, nullable=False),
        sa.Column("agent_profile_id", ID, nullable=False),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("conversation_id", ID, nullable=True),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", EMBEDDING, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_agent_memories_triple",
        "agent_memories",
        ["workspace_id", "agent_profile_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_agent_memories_triple", table_name="agent_memories")
    op.drop_table("agent_memories")