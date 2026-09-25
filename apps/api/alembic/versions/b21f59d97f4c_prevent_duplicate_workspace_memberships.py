"""Prevent duplicate workspace memberships.

Revision ID: b21f59d97f4c
Revises: 0016
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b21f59d97f4c"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT = "uq_workspace_members_workspace_id_user_id"


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM workspace_members
            WHERE id NOT IN (
                SELECT id
                FROM (
                    SELECT id,
                           ROW_NUMBER() OVER (
                               PARTITION BY workspace_id, user_id
                               ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END,
                                        created_at,
                                        id
                           ) AS row_number
                    FROM workspace_members
                ) ranked
                WHERE row_number = 1
            )
            """
        )
    )
    if bind.dialect.name == "sqlite":
        op.create_index(
            CONSTRAINT,
            "workspace_members",
            ["workspace_id", "user_id"],
            unique=True,
        )
    else:
        op.create_unique_constraint(
            CONSTRAINT,
            "workspace_members",
            ["workspace_id", "user_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.drop_index(CONSTRAINT, table_name="workspace_members")
    else:
        op.drop_constraint(CONSTRAINT, "workspace_members", type_="unique")
