from datetime import timedelta

import pytest
from sqlalchemy import select

from src.core.dates import now_utc
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.core import Invitation, Notification
from src.models.workspace import Workspace
from src.seed import DEMO_PASSWORD
from src.seed import main as seed_main
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService
from src.settings import settings


@pytest.fixture
def single_workspace_on(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", True)


async def _workspaces() -> dict[str, str]:
    async with SessionFactory() as session:
        stmt = select(Workspace).order_by(Workspace.created_at, Workspace.id)
        result = await session.execute(stmt)
        return {workspace.id: workspace.slug for workspace in result.scalars()}


async def test_seed_creates_only_first_workspace_in_single_mode(single_workspace_on):
    await seed_main()

    assert list((await _workspaces()).values()) == ["acme-corp"]


async def test_seed_reuses_oldest_workspace_in_single_mode(single_workspace_on, monkeypatch):
    # Create both fixtures with the flag off: in single mode the second
    # create_workspace() is rejected by design.
    monkeypatch.setattr(settings, "single_workspace", False)
    async with SessionFactory() as session:
        owner = await AuthService(session).register(
            email="admin@example.com",
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
        )
        service = WorkspaceService(session)
        first = await service.create_workspace(
            name="First", slug="first", description=None, owner=owner
        )
        second = await service.create_workspace(
            name="Second", slug="second", description=None, owner=owner
        )
        first.created_at = now_utc() - timedelta(days=1)
        second.created_at = now_utc()
        await session.commit()
        first_id, second_id = first.id, second.id

    monkeypatch.setattr(settings, "single_workspace", True)
    await seed_main()

    assert await _workspaces() == {first_id: "first", second_id: "second"}
    async with SessionFactory() as session:
        first_key = await session.scalar(select(ApiKey.id).where(ApiKey.workspace_id == first_id))
        second_key = await session.scalar(select(ApiKey.id).where(ApiKey.workspace_id == second_id))
        assert first_key is not None
        assert second_key is None


async def test_seed_skips_demo_data_for_foreign_single_workspace(single_workspace_on):
    """A workspace created by a non-demo user stays free of demo fixtures.

    A developer who registers before the first seed owns the canonical
    workspace, and the demo admin only gains a membership by logging in.
    """
    async with SessionFactory() as session:
        real = await AuthService(session).register(
            email="real@dev.example",
            password=DEMO_PASSWORD,
            first_name="Real",
            last_name="Dev",
        )
        await WorkspaceService(session).join_single_workspace(real)

    await seed_main()

    assert list((await _workspaces()).values()) == ["workspace"]
    async with SessionFactory() as session:
        for model in (ApiKey, Invitation, Notification):
            result = await session.execute(select(model.id))
            assert result.scalars().all() == [], f"unexpected {model.__name__} rows"


async def test_seed_keeps_both_workspaces_when_single_mode_is_off(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", False)

    await seed_main()

    assert set((await _workspaces()).values()) == {"acme-corp", "globex"}
