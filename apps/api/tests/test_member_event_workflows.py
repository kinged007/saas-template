"""API-level tests: member workflows (joined / role_changed / removed) produce
in-app notifications for the right users, and invitation workflows notify
registered invitees.

The app wires the full workflow registry into the in-process bus, so a
published member event must end up as Notification rows after the background
consumer task runs.
"""

from __future__ import annotations

import asyncio
import inspect

from sqlalchemy import func, select

from src.db.session import SessionFactory
from src.models.core import Notification


async def _count_notifications(user_id: str, type: str) -> int:
    async with SessionFactory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.type == type)
        )
        return result.scalar_one()


async def _wait_for(predicate, timeout_secs: float = 3.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_secs
    while loop.time() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(interval)
    return False


async def _count_ge(user_id: str, type: str, expected: int) -> bool:
    return await _count_notifications(user_id, type) >= expected


async def _count_eq(user_id: str, type: str, expected: int) -> bool:
    return await _count_notifications(user_id, type) == expected


async def _wait_for_count(user_id: str, type: str, expected: int) -> None:
    assert await _wait_for(lambda: _count_ge(user_id, type, expected))


async def _roles_by_name(client, tokens, workspace_id) -> dict[str, str]:
    resp = await client.get(
        "/api/v1/roles",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Workspace-ID": workspace_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return {r["name"]: r["id"] for r in resp.json()}


async def _invite(client, tokens, workspace_id, role_id, email) -> dict:
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role_id},
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Workspace-ID": workspace_id,
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _accept(client, tokens, token: str) -> None:
    resp = await client.post(
        f"/api/v1/invitations/accept?token={token}",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text


async def _me(client, tokens) -> dict:
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _members(client, tokens, workspace_id) -> list[dict]:
    resp = await client.get(
        "/api/v1/members",
        headers={
            "Authorization": f"Bearer {tokens['access_token']}",
            "X-Workspace-ID": workspace_id,
        },
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


async def test_member_joined_notifies_inviter_and_other_members(app_client):
    from tests.conftest import create_workspace, register_user

    owner = await register_user(app_client, "owner@wf1.com")
    member = await register_user(app_client, "member@wf1.com")
    peer = await register_user(app_client, "peer@wf1.com")
    owner_me, member_me, peer_me = (
        await _me(app_client, owner),
        await _me(app_client, member),
        await _me(app_client, peer),
    )
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    inv_member = await _invite(app_client, owner, ws["id"], roles["editor"], "member@wf1.com")
    inv_peer = await _invite(app_client, owner, ws["id"], roles["editor"], "peer@wf1.com")
    # Registered invitees get an in-app notification.
    await _wait_for_count(member_me["id"], "workspace_invitation", 1)
    await _wait_for_count(peer_me["id"], "workspace_invitation", 1)

    await _accept(app_client, member, inv_member["token"])
    # The inviter is notified; the peer is not an active member yet.
    await _wait_for_count(owner_me["id"], "member_joined", 1)
    assert await _count_notifications(peer_me["id"], "member_joined") == 0
    # The joiner is NOT notified about their own join.
    assert await _count_notifications(member_me["id"], "member_joined") == 0

    await _accept(app_client, peer, inv_peer["token"])
    # Now the other active members (owner + member) are notified of peer's join.
    await _wait_for_count(owner_me["id"], "member_joined", 2)
    await _wait_for_count(member_me["id"], "member_joined", 1)
    assert await _count_notifications(peer_me["id"], "member_joined") == 0


async def test_member_role_changed_notifies_the_member(app_client):
    from tests.conftest import create_workspace, register_user

    owner = await register_user(app_client, "owner@wf2.com")
    member = await register_user(app_client, "member@wf2.com")
    member_me = await _me(app_client, member)
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    invite = await _invite(app_client, owner, ws["id"], roles["editor"], "member@wf2.com")
    await _accept(app_client, member, invite["token"])
    await _wait_for_count(member_me["id"], "workspace_invitation", 1)

    members = await _members(app_client, owner, ws["id"])
    member_row = next(m for m in members if m["email"] == "member@wf2.com")

    resp = await app_client.patch(
        f"/api/v1/members/{member_row['membership_id']}",
        json={"role_id": roles["viewer"]},
        headers={
            "Authorization": f"Bearer {owner['access_token']}",
            "X-Workspace-ID": ws["id"],
        },
    )
    assert resp.status_code == 200, resp.text

    assert await _wait_for(lambda: _count_eq(member_me["id"], "member_role_changed", 1))
    async with SessionFactory() as session:
        result = await session.execute(
            select(Notification)
            .where(
                Notification.user_id == member_me["id"],
                Notification.type == "member_role_changed",
            )
            .order_by(Notification.created_at.desc())
        )
        row = result.scalars().first()
    assert row.payload["from_role"] == "editor"
    assert row.payload["to_role"] == "viewer"


async def test_member_removed_notifies_the_removed_member(app_client):
    from tests.conftest import create_workspace, register_user

    owner = await register_user(app_client, "owner@wf3.com")
    member = await register_user(app_client, "member@wf3.com")
    member_me = await _me(app_client, member)
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    invite = await _invite(app_client, owner, ws["id"], roles["editor"], "member@wf3.com")
    await _accept(app_client, member, invite["token"])

    members = await _members(app_client, owner, ws["id"])
    member_row = next(m for m in members if m["email"] == "member@wf3.com")

    resp = await app_client.delete(
        f"/api/v1/members/{member_row['membership_id']}",
        headers={
            "Authorization": f"Bearer {owner['access_token']}",
            "X-Workspace-ID": ws["id"],
        },
    )
    assert resp.status_code == 204, resp.text

    assert await _wait_for(lambda: _count_eq(member_me["id"], "member_removed", 1))
    async with SessionFactory() as session:
        result = await session.execute(
            select(Notification)
            .where(
                Notification.user_id == member_me["id"],
                Notification.type == "member_removed",
            )
            .order_by(Notification.created_at.desc())
        )
        row = result.scalars().first()
    assert row.payload["removed_by"] == "Test U."


async def test_unregistered_invite_emits_no_in_app_notification(app_client):
    """An invite to an email with no account produces no member.invited event."""
    from tests.conftest import create_workspace, register_user

    owner = await register_user(app_client, "owner@wf4.com")
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    await _invite(app_client, owner, ws["id"], roles["editor"], "stranger@wf4.com")
    await asyncio.sleep(0.1)

    async with SessionFactory() as session:
        result = await session.execute(select(func.count()).select_from(Notification))
        assert result.scalar_one() == 0
