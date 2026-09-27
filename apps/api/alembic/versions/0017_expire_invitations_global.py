"""drop the workspace-scoped expire-invitations job definitions

`invitations.expire_stale` moved from workspace scope to global scope, so one
enabled global row replaces the per-workspace rows. It cannot be left in place:
JobService.sync_definitions matches a definition on the exact (key, workspace_id)
pair, so it would insert a new global row alongside them, and its orphan sweep
filters by key alone, so the key is still live and the old rows are never
disabled — every workspace would keep expiring invitations on its own schedule
alongside the global job.

Deleted rather than disabled, because a global job has a single schedule: there
is no per-workspace cron/enabled state to carry over, and nothing in the codebase
ever removes a definition row, so a disabled leftover would sit in every
workspace's job list permanently. Run history goes with it, in the same order
system.retention_cleanup uses, so no job_run is left pointing at a definition
that no longer exists.

Revision ID: 0017
Revises: 0016
Create Date: 2026-09-26 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

JOB_KEY = "invitations.expire_stale"


def upgrade() -> None:
    bind = op.get_bind()
    # Correlated subqueries rather than IN (:ids) lists: an expanding bindparam
    # sends one parameter per row, which exceeds SQLITE_MAX_VARIABLE_NUMBER and
    # PostgreSQL's 65535-parameter limit on a deployment with many workspaces.
    bind.execute(
        sa.text(
            "DELETE FROM job_logs WHERE run_id IN ("
            "  SELECT id FROM job_runs WHERE definition_id IN ("
            "    SELECT id FROM job_definitions"
            "    WHERE key = :key AND workspace_id IS NOT NULL))"
        ),
        {"key": JOB_KEY},
    )
    bind.execute(
        sa.text(
            "DELETE FROM job_runs WHERE definition_id IN ("
            "  SELECT id FROM job_definitions"
            "  WHERE key = :key AND workspace_id IS NOT NULL)"
        ),
        {"key": JOB_KEY},
    )
    bind.execute(
        sa.text("DELETE FROM job_definitions WHERE key = :key AND workspace_id IS NOT NULL"),
        {"key": JOB_KEY},
    )


def downgrade() -> None:
    # Not reversible: the per-workspace rows are re-provisioned on the next
    # startup only for the scope the spec declares, and a global job has no
    # per-workspace rows to restore. Downgrading the code to workspace scope
    # re-provisions them disabled until an admin enables each one.
    return None
