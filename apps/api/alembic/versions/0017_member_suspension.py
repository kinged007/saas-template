"""workspace member suspension: widen status domain to include suspended

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-17 00:00:00.000000

`workspace_members.status` was `active | invited`; `suspend_member` adds
`suspended`. Suspended rows keep their history but fail membership checks.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "workspace_members"
# The naming convention (src/db/base.py) prefixes ck_<table>_ onto the name of
# every check-constraint operation — batch and plain paths alike — so both
# paths pass the bare suffix and the constraint lands on
# ck_workspace_members_status (pinned by db-check). Databases migrated before
# this change carry the doubled ck_workspace_members_ck_workspace_members_status;
# the drop branch reflects and drops whichever form it finds.
_SUFFIX = "status"
_CONSTRAINT = f"ck_{_TABLE}_{_SUFFIX}"
_LEGACY = f"ck_{_TABLE}_ck_{_TABLE}_{_SUFFIX}"
_STATUSES = ("active", "invited", "suspended")


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_check_constraint(_SUFFIX, sa.column("status").in_(_STATUSES))
    else:
        op.create_check_constraint(_SUFFIX, _TABLE, sa.column("status").in_(_STATUSES))


def downgrade() -> None:
    bind = op.get_bind()
    # Unsafe if suspended rows exist: the downgrade fails loudly instead of
    # silently dropping data. Reactivate them first.
    sqlite = bind.dialect.name == "sqlite"

    def drop(name: str) -> None:
        # The convention re-applies to the name each drop passes: the full
        # name targets the doubled legacy form, the bare suffix the clean one.
        if sqlite:
            with op.batch_alter_table(_TABLE) as batch_op:
                batch_op.drop_constraint(name, type_="check")
        else:
            op.drop_constraint(name, _TABLE, type_="check")

    names = {c["name"] for c in sa.inspect(bind).get_check_constraints(_TABLE)}
    if _LEGACY in names:
        drop(_CONSTRAINT)
    if _CONSTRAINT in names:
        drop(_SUFFIX)
