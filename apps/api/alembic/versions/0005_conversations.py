"""conversations and messages

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-28 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # If the new tables already exist (DB was created via Base.metadata.create_all
    # before this migration was stamped), skip DDL and only run the data grant.
    if inspector.has_table("conversations") and inspector.has_table("messages"):
        # Still run the permission grants below — they are idempotent and needed
        # for workspaces that were created before message permissions existed.
        pass
    else:
        dialect = bind.dialect.name
        ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

        def _ts(name: str, nullable: bool = False) -> sa.Column:
            return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

        def _id(name: str = "id") -> sa.Column:
            return sa.Column(name, ID, primary_key=True)

        def _fk(name: str, nullable: bool = False) -> sa.Column:
            return sa.Column(name, ID, nullable=nullable)

        op.create_table(
            "conversations",
            _id(),
            _fk("workspace_id"),
            _fk("created_by_user_id"),
            sa.Column("title", sa.String(length=300), nullable=True),
            sa.Column("last_message_at", TS, nullable=True),
            sa.Column("last_message_preview", sa.String(length=200), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
        op.create_index("ix_conversations_workspace_id", "conversations", ["workspace_id"])
        op.create_index(
            "ix_conversations_created_by_user_id", "conversations", ["created_by_user_id"]
        )
        op.create_index("ix_conversations_last_message_at", "conversations", ["last_message_at"])

        op.create_table(
            "conversation_participants",
            _id(),
            _fk("conversation_id"),
            sa.Column("participant_type", sa.String(length=10), nullable=False, server_default="user"),
            _fk("participant_id"),
            _fk("user_id", nullable=True),
            _fk("agent_id", nullable=True),
            sa.Column("joined_at", TS, nullable=False),
            sa.Column("last_read_at", TS, nullable=True),
            _fk("last_read_message_id", nullable=True),
            sa.Column("archived_at", TS, nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
            sa.UniqueConstraint(
                "participant_type",
                "conversation_id",
                "participant_id",
                name="uq_conversation_participants_type_conversation_participant",
            ),
        )
        op.create_index(
            "ix_conversation_participants_conversation_id",
            "conversation_participants",
            ["conversation_id"],
        )
        op.create_index(
            "ix_conversation_participants_participant_id",
            "conversation_participants",
            ["participant_id"],
        )
        op.create_index(
            "ix_conversation_participants_user_id", "conversation_participants", ["user_id"]
        )
        op.create_index(
            "ix_conversation_participants_agent_id", "conversation_participants", ["agent_id"]
        )
        op.create_index(
            "ix_conversation_participants_participant_type",
            "conversation_participants",
            ["participant_type"],
        )

        op.create_table(
            "messages",
            _id(),
            _fk("conversation_id"),
            sa.Column("sender_type", sa.String(length=10), nullable=False, server_default="user"),
            _fk("sender_id"),
            _fk("sender_user_id", nullable=True),
            _fk("sender_agent_id", nullable=True),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column("body_html", sa.Text(), nullable=True),
            _ts("created_at"),
            _ts("updated_at"),
        )
        op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
        op.create_index("ix_messages_sender_id", "messages", ["sender_id"])
        op.create_index("ix_messages_sender_user_id", "messages", ["sender_user_id"])
        op.create_index("ix_messages_created_at", "messages", ["created_at"])
        op.create_index("ix_messages_conversation_id_created_at", "messages", ["conversation_id", "created_at"])

    # Data migration: grant message permissions to existing system roles.
    # Mirrors 0002/0004 pattern; keeps existing workspaces in sync without
    # requiring a manual sync_system_role_permissions call.
    import json

    _GRANTS = {
        "admin": ["message:read", "message:send"],
        "editor": ["message:read", "message:send"],
        "viewer": ["message:read", "message:send"],
    }
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, name, permissions FROM roles WHERE system = :system"),
        {"system": True},
    ).mappings()
    for row in rows:
        grants = _GRANTS.get(row["name"])
        if not grants:
            continue
        current = row["permissions"]
        if isinstance(current, str):
            current = json.loads(current) if current else []
        updated = list(current) + [p for p in grants if p not in current]
        if updated != current:
            conn.execute(
                sa.text("UPDATE roles SET permissions = :permissions WHERE id = :id"),
                {"permissions": json.dumps(updated), "id": row["id"]},
            )


def downgrade() -> None:
    op.drop_index("ix_messages_conversation_id_created_at", table_name="messages")
    op.drop_index("ix_messages_created_at", table_name="messages")
    op.drop_index("ix_messages_sender_user_id", table_name="messages")
    op.drop_index("ix_messages_sender_id", table_name="messages")
    op.drop_index("ix_messages_conversation_id", table_name="messages")
    op.drop_table("messages")

    op.drop_index(
        "ix_conversation_participants_participant_type", table_name="conversation_participants"
    )
    op.drop_index("ix_conversation_participants_agent_id", table_name="conversation_participants")
    op.drop_index("ix_conversation_participants_user_id", table_name="conversation_participants")
    op.drop_index(
        "ix_conversation_participants_participant_id", table_name="conversation_participants"
    )
    op.drop_index(
        "ix_conversation_participants_conversation_id", table_name="conversation_participants"
    )
    op.drop_table("conversation_participants")

    op.drop_index("ix_conversations_last_message_at", table_name="conversations")
    op.drop_index("ix_conversations_created_by_user_id", table_name="conversations")
    op.drop_index("ix_conversations_workspace_id", table_name="conversations")
    op.drop_table("conversations")
