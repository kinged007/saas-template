"""oauth_accounts.email (which linked account is this)

Revision ID: 0021
Revises: 0020
Create Date: 2026-09-25 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("oauth_accounts", sa.Column("email", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("oauth_accounts", "email")
