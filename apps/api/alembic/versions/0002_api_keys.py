"""api keys

Revision ID: 0002
Revises: 0001
Create Date: 2026-08-19 00:00:00.000000

"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()

# Permissions granted to existing seeded roles when apikey permissions land.
_GRANTS = {
    "admin": ["apikey:read", "apikey:manage"],
    "editor": ["apikey:read", "apikey:manage"],
}


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str) -> sa.Column:
        return sa.Column(name, TS, nullable=False, server_default=NOW)

    def _id(name: str = "id") -> sa.Column:
        return sa.Column(name, ID, primary_key=True)

    def _fk(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, ID, nullable=nullable)

    op.create_table(
        "api_keys",
        _id(),
        _fk("workspace_id"),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("key_prefix", sa.String(length=32), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("permissions", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        _fk("created_by_user_id"),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
        sa.UniqueConstraint("key_hash"),
    )
    op.create_index("ix_api_keys_workspace_id", "api_keys", ["workspace_id"])
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"], unique=True)
    op.create_index("ix_api_keys_created_by_user_id", "api_keys", ["created_by_user_id"])

    # Data migration: workspaces created before the apikey permissions existed
    # still carry the old seeded role permissions. Grant the new permissions to
    # the matching system roles so existing users can manage API keys.
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
    op.drop_index("ix_api_keys_created_by_user_id", table_name="api_keys")
    op.drop_index("ix_api_keys_key_hash", table_name="api_keys")
    op.drop_index("ix_api_keys_workspace_id", table_name="api_keys")
    op.drop_table("api_keys")