"""scheduled jobs framework

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-24 00:00:00.000000

Creates the job_definitions / job_runs / job_logs tables, adds the
users.is_superuser bootstrap flag (backfilled from SUPERADMIN_EMAIL) and
grants the new jobs:view / jobs:edit permissions to existing system roles.

Only admins get jobs permissions by default (owners hold "*"); editors and
viewers must be granted jobs:view explicitly by an admin.
"""

import json
import os
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NOW = sa.func.now()

# Permissions granted to existing seeded roles when jobs permissions land.
_GRANTS = {
    "admin": ["jobs:view", "jobs:edit"],
}


def upgrade() -> None:
    dialect = op.get_bind().dialect.name
    ID = PG_UUID(as_uuid=True) if dialect == "postgresql" else sa.String(36)

    def _ts(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, TS, nullable=nullable, server_default=NOW if not nullable else None)

    def _id(name: str = "id") -> sa.Column:
        return sa.Column(name, ID, primary_key=True)

    def _fk(name: str, nullable: bool = False) -> sa.Column:
        return sa.Column(name, ID, nullable=nullable)

    op.create_table(
        "job_definitions",
        _id(),
        sa.Column("key", sa.String(length=200), nullable=False),
        _fk("workspace_id", nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cron_schedule", sa.String(length=100), nullable=False),
        sa.Column("params_schema", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("missed_policy", sa.String(length=10), nullable=False, server_default="single"),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("next_run_at", TS, nullable=True),
        sa.Column("last_run_at", TS, nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_job_definitions_key", "job_definitions", ["key"])
    op.create_index("ix_job_definitions_workspace_id", "job_definitions", ["workspace_id"])

    op.create_table(
        "job_runs",
        _id(),
        _fk("definition_id"),
        _fk("workspace_id", nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("trigger", sa.String(length=10), nullable=False, server_default="scheduled"),
        _fk("actor_user_id", nullable=True),
        sa.Column("params", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("scheduled_at", TS, nullable=False),
        sa.Column("started_at", TS, nullable=True),
        sa.Column("finished_at", TS, nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("ix_job_runs_definition_id", "job_runs", ["definition_id"])
    op.create_index("ix_job_runs_workspace_id", "job_runs", ["workspace_id"])
    op.create_index("ix_job_runs_status", "job_runs", ["status"])
    op.create_index("ix_job_runs_actor_user_id", "job_runs", ["actor_user_id"])

    op.create_table(
        "job_logs",
        _id(),
        _fk("run_id"),
        sa.Column("seq", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ts", TS, nullable=False),
        sa.Column("level", sa.String(length=10), nullable=False, server_default="INFO"),
        sa.Column("message", sa.Text(), nullable=False),
    )
    op.create_index("ix_job_logs_run_id", "job_logs", ["run_id"])

    # users.is_superuser + backfill from the SUPERADMIN_EMAIL env var.
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.add_column(
                sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false())
            )
    else:
        op.add_column(
            "users",
            sa.Column("is_superuser", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    superadmin_email = os.environ.get("SUPERADMIN_EMAIL", "").strip().lower()
    if superadmin_email:
        bind.execute(
            sa.text("UPDATE users SET is_superuser = true WHERE LOWER(email) = :email"),
            {"email": superadmin_email},
        )

    # Data migration: grant jobs permissions to existing system roles.
    rows = bind.execute(
        sa.text("SELECT id, name, permissions FROM roles WHERE system = :system"),
        {"system": True},
    ).mappings()
    for row in rows:
        grants = _GRANTS.get(row["name"])
        if not grants:
            continue
        current = row["permissions"]
        if isinstance(current, str):
            current = json.loads(current) if current else []
        updated = list(current) + [p for p in grants if p not in current]
        if updated != current:
            bind.execute(
                sa.text("UPDATE roles SET permissions = :permissions WHERE id = :id"),
                {"permissions": json.dumps(updated), "id": row["id"]},
            )


def downgrade() -> None:
    op.drop_index("ix_job_logs_run_id", table_name="job_logs")
    op.drop_table("job_logs")
    op.drop_index("ix_job_runs_actor_user_id", table_name="job_runs")
    op.drop_index("ix_job_runs_status", table_name="job_runs")
    op.drop_index("ix_job_runs_workspace_id", table_name="job_runs")
    op.drop_index("ix_job_runs_definition_id", table_name="job_runs")
    op.drop_table("job_runs")
    op.drop_index("ix_job_definitions_workspace_id", table_name="job_definitions")
    op.drop_index("ix_job_definitions_key", table_name="job_definitions")
    op.drop_table("job_definitions")

    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("users") as batch_op:
            batch_op.drop_column("is_superuser")
    else:
        op.drop_column("users", "is_superuser")
