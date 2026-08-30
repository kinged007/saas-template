"""chat entity_type + agent_session_ref

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-31 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    # conversations.entity_type
    with op.batch_alter_table("conversations") as batch:
        batch.add_column(sa.Column("entity_type", sa.String(length=30), nullable=False, server_default="chat"))
    if dialect == "postgresql":
        op.execute("ALTER TABLE conversations ALTER COLUMN entity_type DROP DEFAULT")
    else:
        # sqlite: server_default already removed by batch; ensure index
        pass
    try:
        op.create_index("ix_conversations_entity_type", "conversations", ["entity_type"])
    except Exception:
        pass

    # conversation_participants.agent_session_ref
    with op.batch_alter_table("conversation_participants") as batch:
        batch.add_column(sa.Column("agent_session_ref", sa.String(length=500), nullable=True))


def downgrade() -> None:
    try:
        op.drop_index("ix_conversations_entity_type", table_name="conversations")
    except Exception:
        pass
    with op.batch_alter_table("conversation_participants") as batch:
        try:
            batch.drop_column("agent_session_ref")
        except Exception:
            pass
    with op.batch_alter_table("conversations") as batch:
        try:
            batch.drop_column("entity_type")
        except Exception:
            pass
