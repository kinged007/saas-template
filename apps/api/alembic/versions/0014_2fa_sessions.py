"""2FA sessions + TOTP backup codes

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-16 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    op.add_column(
        "users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
    )
    op.add_column("refresh_tokens", sa.Column("ip_address", sa.String(length=64), nullable=True))
    op.add_column("refresh_tokens", sa.Column("user_agent", sa.String(length=500), nullable=True))

    op.create_table(
        "user_totp_credentials",
        sa.Column("user_id", ID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("secret_ciphertext", sa.Text(), nullable=False),
        sa.Column("last_counter", sa.Integer(), nullable=True),
        sa.Column("backup_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )


def downgrade() -> None:
    op.drop_table("user_totp_credentials")
    op.drop_column("refresh_tokens", "user_agent")
    op.drop_column("refresh_tokens", "ip_address")
    op.drop_column("users", "totp_enabled")
