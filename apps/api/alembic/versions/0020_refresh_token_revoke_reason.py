"""refresh token revoke reason

Revision ID: 0020
Revises: 0019
Create Date: 2026-09-30 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "refresh_tokens"
# The naming convention (src/db/base.py) prefixes ck_<table>_ onto the name of
# every check-constraint operation — batch and plain paths alike — so both
# paths pass the bare suffix and the constraint lands on
# ck_refresh_tokens_revoke_reason (pinned by db-check). Databases migrated
# before this change carry the doubled
# ck_refresh_tokens_ck_refresh_tokens_revoke_reason; the drop branch reflects
# and drops whichever form it finds.
_SUFFIX = "revoke_reason"
_CONSTRAINT = f"ck_{_TABLE}_{_SUFFIX}"
_LEGACY = f"ck_{_TABLE}_ck_{_TABLE}_{_SUFFIX}"
# The database copy of RevokeReason (src/models/workspace.py). The reuse signal
# keys off this column, so the set is enforced by the database rather than by an
# annotation no type checker in this repo reads.
_REASONS = "'rotated', 'user', 'logout', 'password', 'reuse'"
_SQL = f"revoke_reason IS NULL OR revoke_reason IN ({_REASONS})"


def _create_constraint() -> None:
    bind = op.get_bind()
    names = {c["name"] for c in sa.inspect(bind).get_check_constraints(_TABLE)}
    if _CONSTRAINT in names:
        return
    # sqlite cannot ALTER a table to add a constraint; batch mode rebuilds it.
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table(_TABLE) as batch_op:
            batch_op.create_check_constraint(_SUFFIX, sa.text(_SQL))
    else:
        op.create_check_constraint(_SUFFIX, _TABLE, sa.text(_SQL))


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if "revoke_reason" not in cols:
        op.add_column(
            _TABLE,
            sa.Column("revoke_reason", sa.String(20), nullable=True),
        )
        # Existing rows carry a revoked_at but no reason, so they read as
        # "revoked by unknown means" and never arm the reuse signal.
        op.execute(
            "UPDATE refresh_tokens SET revoke_reason = 'user' "
            "WHERE revoked_at IS NOT NULL AND revoke_reason IS NULL"
        )
    _create_constraint()


def downgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns(_TABLE)}
    if "revoke_reason" in cols:
        names = {c["name"] for c in sa.inspect(bind).get_check_constraints(_TABLE)}
        sqlite = bind.dialect.name == "sqlite"

        def drop(name: str) -> None:
            # The convention re-applies to the name each drop passes: the full
            # name targets the doubled legacy form, the bare suffix the clean
            # one.
            if sqlite:
                with op.batch_alter_table(_TABLE) as batch_op:
                    batch_op.drop_constraint(name, type_="check")
            else:
                op.drop_constraint(name, _TABLE, type_="check")

        if _LEGACY in names:
            drop(_CONSTRAINT)
        if _CONSTRAINT in names:
            drop(_SUFFIX)
        op.drop_column(_TABLE, "revoke_reason")
