"""converge historical drift: drop legacy unique constraints + columns

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-21 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables where the pre-convention migrations declared BOTH a named
# UniqueConstraint and a same-column unique index (0001/0002) — or, for
# auth_tokens, a unique=True column (0010 renders an implicit UQ on
# postgres) plus an explicit unique index. The models declare unique=True
# + index=True on one column, which renders as a single unique index, so
# the leftover standalone constraint is redundant (and confuses
# autogenerate). Each name below was verified present in the migration
# that created it — not inferred from the naming convention — so the drop
# loop only removes a duplicate when the unique index beside it keeps
# enforcing uniqueness.
_REDUNDANT_UQ = {
    "users": ("email", "ix_users_email"),
    "workspaces": ("slug", "ix_workspaces_slug"),
    "refresh_tokens": ("token_hash", "ix_refresh_tokens_token_hash"),
    "api_keys": ("key_hash", "ix_api_keys_key_hash"),
    "auth_tokens": ("token_hash", "ix_auth_tokens_token_hash"),
    "invitations": ("token", "ix_invitations_token"),
}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    # sqlite has no ALTER CONSTRAINT — constraint/index ops below are
    # postgres-only; sqlite test DBs are built by create_all (see
    # tests/conftest.py), which already matches the models.
    pg = bind.dialect.name != "sqlite"

    uq_names = {u["name"] for u in insp.get_unique_constraints("notification_preferences")}
    if pg and "uq_notification_preferences_unsubscribe_token" in uq_names:
        op.drop_constraint(
            "uq_notification_preferences_unsubscribe_token",
            "notification_preferences",
            type_="unique",
        )

    for table, (col, unique_index) in _REDUNDANT_UQ.items():
        uq_name = f"uq_{table}_{col}"
        names = {u["name"] for u in insp.get_unique_constraints(table)}
        indexes = {i["name"] for i in insp.get_indexes(table)}
        if pg and uq_name in names and unique_index in indexes:
            op.drop_constraint(uq_name, table, type_="unique")

    indexes = {i["name"] for i in insp.get_indexes("stored_secrets")}
    if "ix_stored_secrets_secret_key" not in indexes:
        op.create_index(
            "ix_stored_secrets_secret_key", "stored_secrets", ["secret_key"], unique=False
        )

    cols = {c["name"] for c in insp.get_columns("stored_secrets")}
    if "key_id" in cols:
        op.drop_column("stored_secrets", "key_id")

    if pg:
        # Model history widened StoredSecret.meta to nullable (see secret.py);
        # 0001 created it NOT NULL, so converge the column to the model.
        op.alter_column(
            "stored_secrets",
            "meta",
            existing_type=sa.JSON(),
            type_=sa.JSON(),
            existing_nullable=False,
            nullable=True,
        )

        # secret_key stays at the migrated String(500) width (model now
        # matches it). The no-op alter normalizes the type on postgres so
        # the column renders identically on both dialects.
        op.alter_column(
            "stored_secrets",
            "secret_key",
            existing_type=sa.String(length=500),
            type_=sa.String(length=500),
            existing_nullable=False,
        )


def downgrade() -> None:
    # Reverse every upgrade step so downgrade → upgrade is round-trip clean.
    # sqlite guards mirror upgrade: sqlite DBs are create_all-built, so
    # downgrade constraint/alter ops are postgres-only.
    bind = op.get_bind()
    insp = sa.inspect(bind)
    bind_name = bind.dialect.name
    pg = bind_name != "sqlite"

    if pg:
        op.alter_column(
            "stored_secrets",
            "meta",
            existing_type=sa.JSON(),
            type_=sa.JSON(),
            existing_nullable=True,
            nullable=False,
        )

        op.alter_column(
            "stored_secrets",
            "secret_key",
            existing_type=sa.String(length=500),
            type_=sa.String(length=500),
            existing_nullable=False,
        )

    cols = {c["name"] for c in insp.get_columns("stored_secrets")}
    if "key_id" not in cols:
        op.add_column(
            "stored_secrets",
            sa.Column("key_id", sa.String(length=200), nullable=True),
        )

    indexes = {i["name"] for i in insp.get_indexes("stored_secrets")}
    if pg and "ix_stored_secrets_secret_key" in indexes:
        op.drop_index("ix_stored_secrets_secret_key", table_name="stored_secrets")

    # Intentional divergence, the six below: the recreated UQs restore the
    # pre-0013 schema but models no longer declare them (unique+index renders
    # as unique index only), so autogenerate reports drift until re-upgrade.
    for table, (col, _unique_index) in _REDUNDANT_UQ.items():
        uq_name = f"uq_{table}_{col}"
        names = {u["name"] for u in insp.get_unique_constraints(table)}
        if pg and uq_name not in names:
            op.create_unique_constraint(uq_name, table, [col])

    # Different case from the six above: no migration ever created this UQ
    # (0009 declared unsubscribe_token as a plain column with a non-unique
    # index) and the model does not declare it either, so recreating it
    # restores a shape that never existed rather than a pre-0013 one. The
    # round-trip stays net-neutral because the matching drop in upgrade()
    # removes it again on re-upgrade; the guard below is what makes that drop
    # land on a clean downgrade-then-upgrade cycle instead of failing on an
    # already-constrained table, and why the create fires unconditionally on a
    # freshly downgraded postgres.
    uq_names = {u["name"] for u in insp.get_unique_constraints("notification_preferences")}
    if pg and "uq_notification_preferences_unsubscribe_token" not in uq_names:
        op.create_unique_constraint(
            "uq_notification_preferences_unsubscribe_token",
            "notification_preferences",
            ["unsubscribe_token"],
        )
