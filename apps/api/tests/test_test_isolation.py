"""Canary for the per-test database fixture.

Each test here relies on the autouse `_clean_db` fixture for its database and
does no cleanup of its own. A leak from an earlier test is therefore a failure
of this file, not a test-authoring mistake.
"""

import pytest
from sqlalchemy import func, inspect, select

from src.models.core import Notification
from src.models.workspace import User, Workspace
from tests.conftest import create_workspace, register_user


async def _count(model) -> int:
    from src.db.session import SessionFactory

    async with SessionFactory() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def test_a_write_leaves_rows_behind(app_client):
    """Leaves one user and one workspace behind on purpose."""
    tokens = await register_user(app_client)
    await create_workspace(app_client, tokens)

    assert await _count(User) == 1
    assert await _count(Workspace) == 1


async def test_no_rows_leak_between_tests():
    assert await _count(User) == 0
    assert await _count(Workspace) == 0


async def test_stale_writer_cannot_reach_next_test(app_client):
    """Create a workspace, which publishes `workspaces.created`, and return
    without draining the bus. The workflow's writes must not outlive this
    test's database."""
    tokens = await register_user(app_client)
    await create_workspace(app_client, tokens, name="Stale Writer Co")


async def test_workflow_rows_do_not_survive_the_publishing_test():
    assert await _count(Notification) == 0


@pytest.mark.parametrize("table", ["users", "workspaces", "notifications"])
async def test_each_test_gets_a_fresh_database_file(tmp_path, table):
    """The database is a new file inside this test's own tmp_path, not one
    shared file emptied in place."""
    from src.db.session import engine

    assert str(tmp_path) in str(engine.url)
    async with engine.connect() as conn:
        names = await conn.run_sync(lambda sync_conn: inspect(sync_conn).get_table_names())
    assert table in names
