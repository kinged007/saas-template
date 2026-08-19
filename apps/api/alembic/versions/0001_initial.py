"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-08-18 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    # Detect dialect at runtime for UUID type selection
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str) -> sa.Column:
        return sa.Column(name, TS, nullable=False, server_default=NOW)

    def _id(name: str = "id") -> sa.Column:
        return sa.Column(name, ID, primary_key=True)

    def _fk(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, ID, nullable=nullable)

    op.create_table(
        "users",
        _id(),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=128), nullable=True),
        sa.Column("display_name", sa.String(length=150), nullable=False),
        sa.Column("avatar_url", sa.String(length=500), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("last_login_at", TS, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "workspaces",
        _id(),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=True),
        _fk("created_by_user_id"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index("ix_workspaces_slug", "workspaces", ["slug"], unique=True)
    op.create_index("ix_workspaces_created_by_user_id", "workspaces", ["created_by_user_id"])

    op.create_table(
        "refresh_tokens",
        _id(),
        _fk("user_id"),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("revoked_at", TS, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_user_id", "refresh_tokens", ["user_id"])
    op.create_index("ix_refresh_tokens_token_hash", "refresh_tokens", ["token_hash"], unique=True)

    op.create_table(
        "roles",
        _id(),
        _fk("workspace_id"),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("description", sa.String(length=300), nullable=True),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("system", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_roles_workspace_id", "roles", ["workspace_id"])

    op.create_table(
        "invitations",
        _id(),
        _fk("workspace_id"),
        sa.Column("email", sa.String(length=320), nullable=False),
        _fk("role_id"),
        _fk("invited_by_user_id"),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("expires_at", TS, nullable=False),
        sa.Column("accepted_at", TS, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_invitations_workspace_id", "invitations", ["workspace_id"])
    op.create_index("ix_invitations_token", "invitations", ["token"], unique=True)

    op.create_table(
        "notifications",
        _id(),
        _fk("user_id"),
        _fk("workspace_id"),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("body", sa.String(length=2000), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("acknowledged_at", TS, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_notifications_user_id", "notifications", ["user_id"])
    op.create_index("ix_notifications_workspace_id", "notifications", ["workspace_id"])

    op.create_table(
        "workspace_members",
        _id(),
        _fk("workspace_id"),
        _fk("user_id"),
        _fk("role_id"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'active'")),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_workspace_members_workspace_id", "workspace_members", ["workspace_id"])
    op.create_index("ix_workspace_members_user_id", "workspace_members", ["user_id"])
    op.create_index("ix_workspace_members_role_id", "workspace_members", ["role_id"])

    op.create_table(
        "stored_secrets",
        _id(),
        _fk("workspace_id"),
        sa.Column("secret_key", sa.String(length=500), nullable=False),
        sa.Column("ciphertext", sa.Text(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=50), nullable=False),
        sa.Column("label", sa.String(length=300), nullable=True),
        sa.Column("key_id", sa.String(length=200), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_stored_secrets_workspace_id", "stored_secrets", ["workspace_id"])

    op.create_table(
        "audit_log_entries",
        _id(),
        _fk("workspace_id"),
        _fk("actor_user_id", nullable=True),
        sa.Column("resource_type", sa.String(length=100), nullable=False),
        sa.Column("resource_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_audit_log_entries_workspace_id", "audit_log_entries", ["workspace_id"])


def downgrade() -> None:
    op.drop_table("audit_log_entries")
    op.drop_table("stored_secrets")
    op.drop_table("workspace_members")
    op.drop_table("notifications")
    op.drop_table("invitations")
    op.drop_table("roles")
    op.drop_table("refresh_tokens")
    op.drop_table("workspaces")
    op.drop_table("users")
