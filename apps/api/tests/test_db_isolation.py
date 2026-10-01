from __future__ import annotations

import aiosqlite
import pytest
from sqlalchemy import inspect, text

from src.db.session import engine

from .conftest import _db_path

# Connections the tests below deliberately leave behind, standing in for a bus
# worker or job task that is still draining when a test ends. Module-scoped
# teardown holds each leak across every fixture cycle that follows it, and runs
# however pytest selects from this file, so cleanup is never skipped.
_leaked: list[aiosqlite.Connection] = []


@pytest.fixture(scope="module", autouse=True)
async def _close_leaked_connections():
    yield
    while _leaked:
        await _leaked.pop().close()


async def _table_names() -> set[str]:
    async with engine.begin() as conn:
        return set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))


async def test_leaked_write_transaction_does_not_break_the_next_test():
    conn = await aiosqlite.connect(_db_path())
    _leaked.append(conn)
    await conn.execute("CREATE TABLE leak_scratch (id INTEGER PRIMARY KEY)")
    await conn.execute("INSERT INTO leak_scratch (id) VALUES (1)")
    # Never committed: the connection keeps sqlite's write lock and a read
    # snapshot, so any other connection to the same file is either locked out
    # of DDL or reads a schema that predates the next test's create_all.


async def test_schema_survives_a_leaked_connection():
    tables = await _table_names()
    assert "leak_scratch" not in tables, "the leaked test's table survived the reset"
    assert {"users", "workspaces", "workspace_members"} <= tables, "schema is incomplete"
    async with engine.connect() as conn:
        # A stale snapshot makes create_all a no-op: the table is in the
        # catalog but not for the next read.
        await conn.execute(text("SELECT count(*) FROM users"))  # raises if unreadable


async def test_committed_row_does_not_survive_into_the_next_test():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE reset_scratch (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO reset_scratch (id) VALUES (1)"))


async def test_committed_row_is_gone_after_the_reset():
    assert "reset_scratch" not in await _table_names()
