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

_CONSTRAINT = "ck_refresh_tokens_revoke_reason"
# batch_alter_table() applies the ck_<table>_ prefix itself, so it takes the
# bare suffix; the plain path takes the full name. Passing the full name to
# both lands the sqlite constraint on ck_refresh_tokens_ck_refresh_tokens_*.
_BATCH_CONSTRAINT = _CONSTRAINT.removeprefix("ck_refresh_tokens_")
# The database copy of RevokeReason (src/models/workspace.py). The reuse signal
# keys off this column, so the set is enforced by the database rather than by an
# annotation no type checker in this repo reads.
_REASONS = "'rotated', 'user', 'logout', 'password', 'reuse'"
_SQL = f"revoke_reason IS NULL OR revoke_reason IN ({_REASONS})"


def _create_constraint() -> None:
    bind = op.get_bind()
    names = {c["name"] for c in sa.inspect(bind).get_check_constraints("refresh_tokens")}
    if _CONSTRAINT in names:
        return
    # sqlite cannot ALTER a table to add a constraint; batch mode rebuilds it.
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("refresh_tokens") as batch_op:
            batch_op.create_check_constraint(_BATCH_CONSTRAINT, sa.text(_SQL))
    else:
        op.create_check_constraint(_CONSTRAINT, "refresh_tokens", sa.text(_SQL))


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("refresh_tokens")}
    if "revoke_reason" not in cols:
        op.add_column(
            "refresh_tokens",
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
    cols = {c["name"] for c in sa.inspect(bind).get_columns("refresh_tokens")}
    if "revoke_reason" in cols:
        if bind.dialect.name == "sqlite":
            with op.batch_alter_table("refresh_tokens") as batch_op:
                batch_op.drop_constraint(_BATCH_CONSTRAINT, type_="check")
        else:
            op.drop_constraint(_CONSTRAINT, "refresh_tokens", type_="check")
        op.drop_column("refresh_tokens", "revoke_reason")
