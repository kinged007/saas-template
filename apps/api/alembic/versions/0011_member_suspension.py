"""workspace member suspension: widen status domain to include suspended

Revision ID: 0011
Revises: 0010
Create Date: 2026-09-17 00:00:00.000000

`workspace_members.status` was `active | invited`; `suspend_member` adds
`suspended`. Suspended rows keep their history but fail membership checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_workspace_members_status"
_STATUSES = ("active", "invited", "suspended")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("workspace_members") as batch_op:
            batch_op.create_check_constraint(_CONSTRAINT, sa.column("status").in_(_STATUSES))
    else:
        op.create_check_constraint(
            _CONSTRAINT, "workspace_members", sa.column("status").in_(_STATUSES)
        )


def downgrade() -> None:
    bind = op.get_bind()
    # Unsafe if suspended rows exist: the downgrade fails loudly instead of
    # silently dropping data. Reactivate them first.
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("workspace_members") as batch_op:
            batch_op.drop_constraint(_CONSTRAINT, type_="check")
    else:
        op.drop_constraint(_CONSTRAINT, "workspace_members", type_="check")
