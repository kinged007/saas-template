from datetime import timedelta

import pytest
from sqlalchemy import select

from src.core.dates import now_utc
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.workspace import Workspace
from src.seed import DEMO_PASSWORD, main as seed_main
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService
from src.settings import settings


@pytest.fixture
def single_workspace_on(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", True)


async def _workspaces() -> dict[str, str]:
    async with SessionFactory() as session:
        result = await session.execute(select(Workspace).order_by(Workspace.created_at, Workspace.id))
        return {workspace.id: workspace.slug for workspace in result.scalars()}


async def test_seed_creates_only_first_workspace_in_single_mode(single_workspace_on):
    await seed_main()

    assert list((await _workspaces()).values()) == ["acme-corp"]


async def test_seed_reuses_oldest_workspace_in_single_mode(
    single_workspace_on, monkeypatch
):
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


async def test_seed_keeps_both_workspaces_when_single_mode_is_off(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", False)

    await seed_main()

    assert set((await _workspaces()).values()) == {"acme-corp", "globex"}
