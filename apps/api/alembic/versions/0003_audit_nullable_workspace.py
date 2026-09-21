"""audit log: workspace_id nullable (user-scoped audit entries)

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-20 00:00:00.000000

Audit entries now also cover user-scoped actions (auth: register/login/
logout/token refresh) which have no workspace, so the column becomes nullable.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("audit_log_entries") as batch_op:
            batch_op.alter_column("workspace_id", existing_type=sa.String(36), nullable=True)
    else:
        op.alter_column("audit_log_entries", "workspace_id", nullable=True)


def downgrade() -> None:
    # Dropping user-scoped rows would corrupt the trail; the downgrade is
    # intentionally unsafe if such rows exist.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("audit_log_entries") as batch_op:
            batch_op.alter_column("workspace_id", existing_type=sa.String(36), nullable=False)
    else:
        op.alter_column("audit_log_entries", "workspace_id", nullable=False)
