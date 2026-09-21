"""webhook subscriptions + deliveries; webhook permissions for system roles

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-14 00:00:00.000000
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

_GRANTS = {
    "admin": ["webhook:read", "webhook:manage"],
}


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

    def _id(name: str = "id") -> sa.Column:
        return sa.Column(name, ID, primary_key=True)

    def _fk(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, ID, nullable=nullable)

    op.create_table(
        "webhook_subscriptions",
        _id(),
        _fk("workspace_id"),
        sa.Column("url", sa.String(length=2000), nullable=False),
        sa.Column("events", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        _fk("created_by_user_id", nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_webhook_subscriptions_workspace_id", "webhook_subscriptions", ["workspace_id"]
    )

    op.create_table(
        "webhook_deliveries",
        _id(),
        _fk("subscription_id"),
        _fk("workspace_id"),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("subject", sa.String(length=100), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_retry_at", TS, nullable=True),
        sa.Column("last_attempt_at", TS, nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("event_id", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index(
        "ix_webhook_deliveries_subscription_id", "webhook_deliveries", ["subscription_id"]
    )
    op.create_index("ix_webhook_deliveries_workspace_id", "webhook_deliveries", ["workspace_id"])
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])

    # Data migration: grant webhook permissions to existing system roles
    # (owners hold "*" already; sync_system_role_permissions converges the rest).
    import json

    bind = op.get_bind()
    rows = bind.execute(
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
            bind.execute(
                sa.text("UPDATE roles SET permissions = :permissions WHERE id = :id"),
                {"permissions": json.dumps(updated), "id": row["id"]},
            )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_status", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_workspace_id", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_subscription_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")
    op.drop_index("ix_webhook_subscriptions_workspace_id", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")
