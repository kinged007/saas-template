"""Covers the data migration in 0021_expire_invitations_global.

Every other DB test builds the schema from Base.metadata, so no test runs a
migration's raw SQL. 0021 deletes rows, so a regression in it would only show
up on a real deployment.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from src import models as _models  # noqa: F401  (register tables on Base.metadata)
from src.db.base import Base

MIGRATION_PATH = (
    Path(__file__).parents[1] / "alembic" / "versions" / "0021_expire_invitations_global.py"
)
JOB_KEY = "invitations.expire_stale"
OTHER_KEY = "demo.workspace_report"
NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def conn():
    engine = sa.create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        yield connection
    engine.dispose()


def add_definition(conn, def_id, key, workspace_id):
    conn.execute(
        sa.text(
            "INSERT INTO job_definitions (id, key, workspace_id, name, description,"
            " cron_schedule, params_schema, params, enabled, missed_policy, timeout_seconds)"
            " VALUES (:id, :key, :ws, :key, '', '0 3 * * *', '{}', '{}', 0, 'single', 60)"
        ),
        {"id": def_id, "key": key, "ws": workspace_id},
    )


def add_run(conn, run_id, definition_id):
    conn.execute(
        sa.text(
            "INSERT INTO job_runs (id, definition_id, workspace_id, status, trigger, params,"
            " scheduled_at) VALUES (:id, :def, NULL, 'success', 'scheduled', '{}', :at)"
        ),
        {"id": run_id, "def": definition_id, "at": NOW},
    )


def add_log(conn, log_id, run_id):
    conn.execute(
        sa.text(
            "INSERT INTO job_logs (id, run_id, seq, ts, level, message)"
            " VALUES (:id, :run, 0, :at, 'INFO', 'hello')"
        ),
        {"id": log_id, "run": run_id, "at": NOW},
    )


def ids(conn, table):
    return sorted(conn.execute(sa.text(f"SELECT id FROM {table}")).scalars().all())


def test_upgrade_removes_workspace_scoped_definitions_and_their_history(conn):
    add_definition(conn, "d-ws-1", JOB_KEY, "ws-1")
    add_definition(conn, "d-ws-2", JOB_KEY, "ws-2")
    add_definition(conn, "d-ws-other", OTHER_KEY, "ws-1")
    add_definition(conn, "d-global", JOB_KEY, None)
    add_run(conn, "r-ws-1", "d-ws-1")
    add_run(conn, "r-global", "d-global")
    add_run(conn, "r-other", "d-ws-other")
    add_log(conn, "l-ws-1", "r-ws-1")
    add_log(conn, "l-global", "r-global")
    add_log(conn, "l-other", "r-other")

    spec = importlib.util.spec_from_file_location("mig_0021", MIGRATION_PATH)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with Operations.context(MigrationContext.configure(conn)):
        migration.upgrade()

    # The global row and the unrelated workspace job keep their rows and history.
    # The global definition's own run/log must survive: an over-broad DELETE
    # (e.g. dropping AND workspace_id IS NOT NULL) would wipe it as well.
    assert ids(conn, "job_definitions") == ["d-global", "d-ws-other"]
    assert ids(conn, "job_runs") == ["r-global", "r-other"]
    assert ids(conn, "job_logs") == ["l-global", "l-other"]
