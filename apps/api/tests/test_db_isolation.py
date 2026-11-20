from __future__ import annotations

import aiosqlite
import pytest
from sqlalchemy import inspect, text

from src.db.session import engine

from .conftest import _db_path, _fresh_db

# Connections the tests below deliberately leave behind, standing in for a bus
# worker or job task that is still draining when a test ends. Module-scoped
# teardown closes each leak once the module's tests are done, however pytest
# selects from this file, so cleanup is never skipped.
_leaked: list[aiosqlite.Connection] = []


@pytest.fixture(scope="module", autouse=True)
async def _close_leaked_connections():
    yield
    while _leaked:
        await _leaked.pop().close()


async def _table_names() -> set[str]:
    async with engine.begin() as conn:
        return set(await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names()))


async def test_leaked_connection_does_not_block_the_reset():
    conn = await aiosqlite.connect(_db_path())
    _leaked.append(conn)
    await conn.execute("CREATE TABLE leak_scratch (id INTEGER PRIMARY KEY)")
    await conn.execute("INSERT INTO leak_scratch (id) VALUES (1)")
    # Never committed: the connection keeps sqlite's write lock and a read
    # snapshot, so any other connection to the same file is either locked out
    # of DDL or reads a schema that predates the create_all below.

    await _fresh_db()  # the reset the next test's fixture would otherwise do
    tables = await _table_names()
    assert "leak_scratch" not in tables, "the leaked test's table survived the reset"
    assert {"users", "workspaces", "workspace_members"} <= tables, "schema is incomplete"
    async with engine.connect() as read_conn:
        # A stale snapshot makes create_all a no-op: the table is in the
        # catalog but not for the next read.
        await read_conn.execute(text("SELECT count(*) FROM users"))  # raises if unreadable


async def test_committed_row_is_gone_after_the_reset():
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE reset_scratch (id INTEGER PRIMARY KEY)"))
        await conn.execute(text("INSERT INTO reset_scratch (id) VALUES (1)"))
    async with engine.connect() as conn:
        count = await conn.scalar(text("SELECT count(*) FROM reset_scratch"))
    assert count == 1, "the committed row under test never landed"

    await _fresh_db()
    assert "reset_scratch" not in await _table_names(), "reset_scratch survived the database reset"
