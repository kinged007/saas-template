"""`NotificationService.list_for_user` applies the workspace half of its scope."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from tests.conftest import create_workspace, register_user


async def _user_id(client, tokens) -> str:
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _seed(client) -> tuple[str, str, str]:
    """One user, two of that user's own workspaces, and two notifications in
    the first one — the older one backdated, so `list_for_user`'s documented
    ordering has two rows to order."""
    tokens = await register_user(client, "scope@example.com")
    user_id = await _user_id(client, tokens)
    mine = await create_workspace(client, tokens, name="Mine")
    other = await create_workspace(client, tokens, name="Other")

    from src.db.session import SessionFactory
    from src.services.notifications import NotificationService

    async with SessionFactory() as session:
        service = NotificationService(session)
        await service.create(
            user_id=user_id,
            workspace_id=mine["id"],
            type="member_role_changed",
            title="You were added",
        )
        older = await service.create(
            user_id=user_id,
            workspace_id=mine["id"],
            type="member_role_changed",
            title="Older alert",
        )
        older.created_at = datetime.now(UTC) - timedelta(hours=1)
        await session.commit()
    return user_id, mine["id"], other["id"]


async def test_list_for_user_requires_a_workspace(app_client):
    """The workspace predicate is required, not a caller convention: omitting
    it raises instead of silently reading every workspace for the user."""
    from src.db.session import SessionFactory
    from src.services.notifications import NotificationService

    user_id, _, _ = await _seed(app_client)
    async with SessionFactory() as session:
        service = NotificationService(session)
        # `match` pins *which* TypeError: the omitted `workspace_id`, not an
        # incidental one raised somewhere inside the call.
        with pytest.raises(TypeError, match="workspace_id"):
            await service.list_for_user(user_id)


async def test_list_for_user_ignores_a_sibling_workspace(app_client):
    """The fixture gives one user two workspaces, so `other` is a sibling the
    same user owns — the seeded rows are scoped to a workspace other than the
    one asked for, not to another user's workspace."""
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
        # both seeded rows are in scope, newest first as documented
        assert [n.title for n in rows] == ["You were added", "Older alert"]
        # the acknowledged filter still splits within the scope
        assert await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=True) == []
        unacked = await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=False)
        assert len(unacked) == 2

        await service.acknowledge(user_id, rows[0].id, workspace_id=mine_id)
    async with SessionFactory() as session:
        service = NotificationService(session)
        acked = await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=True)
        assert len(acked) == 1
        left = await service.list_for_user(user_id, workspace_id=mine_id, acknowledged=False)
        assert [n.title for n in left] == ["Older alert"]
