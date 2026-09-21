"""notification preferences (per-user channel control + digest flag)

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    op.create_table(
        "notification_preferences",
        sa.Column("id", ID, primary_key=True),
        sa.Column("user_id", ID, nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("channel", sa.String(length=10), nullable=False, server_default="in-app"),
        sa.Column("digest_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("unsubscribe_token", sa.String(length=64), nullable=True),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
        sa.UniqueConstraint("user_id", "type", name="uq_notification_preferences_user_id_type"),
    )
    op.create_index("ix_notification_preferences_user_id", "notification_preferences", ["user_id"])
    op.create_index(
        "ix_notification_preferences_unsubscribe_token",
        "notification_preferences",
        ["unsubscribe_token"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_preferences_unsubscribe_token",
        table_name="notification_preferences",
    )
    op.drop_index("ix_notification_preferences_user_id", table_name="notification_preferences")
    op.drop_table("notification_preferences")
