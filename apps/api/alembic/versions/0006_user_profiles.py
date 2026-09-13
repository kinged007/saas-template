"""user_profiles 1:1

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-29 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if inspector.has_table("user_profiles"):
        # Table already exists (e.g. created via Base.metadata.create_all in tests)
        # Still run backfill idempotently.
        pass
    else:
        dialect = bind.dialect.name
        ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

        def _ts(name: str, nullable: bool = False) -> sa.Column:
            return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

        def _id(name: str = "id") -> sa.Column:
            return sa.Column(name, ID, primary_key=True)

        op.create_table(
            "user_profiles",
            sa.Column("user_id", ID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("first_name", sa.String(length=100), nullable=True),
            sa.Column("last_name", sa.String(length=100), nullable=True),
            sa.Column("bio", sa.String(length=1000), nullable=True),
            sa.Column("phone_number", sa.String(length=30), nullable=True),
            sa.Column("timezone", sa.String(length=50), nullable=True),
            sa.Column("locale", sa.String(length=10), nullable=True),
            sa.Column("date_of_birth", sa.Date(), nullable=True),
            sa.Column("website_url", sa.String(length=500), nullable=True),
            sa.Column("location", sa.String(length=200), nullable=True),
            sa.Column("custom_data", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            _ts("created_at"),
            _ts("updated_at"),
        )

    # Backfill missing profiles idempotently
    conn = op.get_bind()
    dialect = conn.dialect.name
    if dialect == "postgresql":
        conn.execute(
            sa.text("INSERT INTO user_profiles (user_id) SELECT id FROM users ON CONFLICT (user_id) DO NOTHING")
        )
    else:
        conn.execute(sa.text("INSERT OR IGNORE INTO user_profiles (user_id) SELECT id FROM users"))


def downgrade() -> None:
    op.drop_table("user_profiles")
