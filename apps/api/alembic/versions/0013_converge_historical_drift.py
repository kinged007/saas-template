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

# Tables whose models declare unique=True + index=True on one column: that
# renders as a single unique index, so the standalone unique constraint the
# old migrations created is redundant (and confuses autogenerate).
_REDUNDANT_UQ = {
    "users": "email",
    "workspaces": "slug",
    "refresh_tokens": "token_hash",
    "api_keys": "key_hash",
    "auth_tokens": "token_hash",
    "invitations": "token",
}


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    uq_names = {u["name"] for u in insp.get_unique_constraints("notification_preferences")}
    if "uq_notification_preferences_unsubscribe_token" in uq_names:
        op.drop_constraint(
            "uq_notification_preferences_unsubscribe_token",
            "notification_preferences",
            type_="unique",
        )

    for table, col in _REDUNDANT_UQ.items():
        uq_name = f"uq_{table}_{col}"
        names = {u["name"] for u in insp.get_unique_constraints(table)}
        if uq_name in names:
            op.drop_constraint(uq_name, table, type_="unique")

    op.create_index("ix_stored_secrets_secret_key", "stored_secrets", ["secret_key"], unique=False)

    cols = {c["name"] for c in insp.get_columns("stored_secrets")}
    if "key_id" in cols:
        op.drop_column("stored_secrets", "key_id")
    # Model history narrowed secret_key 500 → 400 without a migration;
    # converge back to the migrated width (live keys are prefix-namespaced).
    # ponytail: widen only — narrows need a data check first.
    op.alter_column(
        "stored_secrets",
        "secret_key",
        existing_type=sa.String(length=400),
        type_=sa.String(length=500),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.add_column(
        "stored_secrets",
        sa.Column("key_id", sa.String(length=200), nullable=True),
    )
    op.create_unique_constraint(
        "uq_notification_preferences_unsubscribe_token",
        "notification_preferences",
        ["unsubscribe_token"],
    )
