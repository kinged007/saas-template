"""`NotificationService.list_for_user` applies the workspace half of its scope."""

from __future__ import annotations

import pytest

from tests.conftest import create_workspace, register_user


async def _user_id(client, tokens) -> str:
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed(client) -> tuple[str, str, str]:
    """One user, two workspaces, one notification in the first workspace."""
    tokens = await register_user(client, "scope@example.com")
    user_id = await _user_id(client, tokens)
    mine = await create_workspace(client, tokens, name="Mine")
    other = await create_workspace(client, tokens, name="Other")

    from src.db.session import SessionFactory
    from src.services.notifications import NotificationService

    async with SessionFactory() as session:
        await NotificationService(session).create(
            user_id=user_id,
            workspace_id=mine["id"],
            type="member_role_changed",
            title="You were added",
        )
    return user_id, mine["id"], other["id"]


async def test_list_for_user_requires_a_workspace(app_client):
    """The workspace predicate is required, not a caller convention: omitting
    it raises instead of silently reading every workspace for the user."""
    from src.db.session import SessionFactory
    from src.services.notifications import NotificationService

    user_id, _, _ = await _seed(app_client)
    async with SessionFactory() as session:
        service = NotificationService(session)
        with pytest.raises(TypeError):
            await service.list_for_user(user_id)


async def test_list_for_user_ignores_a_foreign_workspace(app_client):
    from src.db.session import SessionFactory
    from src.services.notifications import NotificationService

    user_id, _, other_id = await _seed(app_client)
    async with SessionFactory() as session:
        service = NotificationService(session)
        assert await service.list_for_user(user_id, workspace_id=other_id) == []


async def test_list_for_user_returns_rows_for_its_own_workspace(app_client):
    from src.db.session import SessionFactory
    from src.services.notifications import NotificationService

    user_id, mine_id, _ = await _seed(app_client)
    async with SessionFactory() as session:
        service = NotificationService(session)
        rows = await service.list_for_user(user_id, workspace_id=mine_id)
        assert [n.title for n in rows] == ["You were added"]
        # the acknowledged filter still splits within the scope
        assert await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=True) == []
        unacked = await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=False)
        assert len(unacked) == 1

        await service.acknowledge(user_id, rows[0].id, workspace_id=mine_id)
    async with SessionFactory() as session:
        service = NotificationService(session)
        acked = await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=True)
        assert len(acked) == 1
        assert await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=False) == []
