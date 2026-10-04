"""file upload metadata

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-17 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    op.create_table(
        "file_objects",
        sa.Column("id", ID, primary_key=True),
        sa.Column(
            "workspace_id", ID, sa.ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "owner_user_id", ID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=127), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False, server_default=NOW),
        sa.Column("updated_at", TS, nullable=False, server_default=NOW),
    )
    op.create_index("ix_file_objects_workspace_id", "file_objects", ["workspace_id"])
    op.create_index("ix_file_objects_owner_user_id", "file_objects", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_file_objects_owner_user_id", table_name="file_objects")
    op.drop_index("ix_file_objects_workspace_id", table_name="file_objects")
    op.drop_table("file_objects")
