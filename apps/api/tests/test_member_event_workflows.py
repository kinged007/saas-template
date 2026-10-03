"""API-level tests: member workflows (joined / role_changed / removed) produce
in-app notifications for the right users, and invitation workflows notify
registered invitees and email unregistered ones.

The app wires the full workflow registry into the in-process bus, so a
published member event must end up as Notification rows after the background
consumer task runs.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid

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


async def _latest_role_change(user_id: str):
    async with SessionFactory() as session:
        result = await session.execute(
            select(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.type == "member_role_changed",
            )
            .order_by(Notification.created_at.desc())
        )
        return result.scalars().first()


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
    # Someone else made the change: the body stays third person.
    assert row.body.endswith("changed your role from editor to viewer.")


async def test_admin_demoting_themselves_reads_neutrally(app_client):
    """The actor is the member, so the body must not name them."""
    from tests.conftest import create_workspace, register_user

    owner = await register_user(app_client, "owner@wf-self.com")
    admin = await register_user(app_client, "admin@wf-self.com")
    admin_me = await _me(app_client, admin)
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    invite = await _invite(app_client, owner, ws["id"], roles["admin"], "admin@wf-self.com")
    await _accept(app_client, admin, invite["token"])

    admin_row = next(
        m for m in await _members(app_client, owner, ws["id"]) if m["email"] == "admin@wf-self.com"
    )
    resp = await app_client.patch(
        f"/api/v1/members/{admin_row['membership_id']}",
        json={"role_id": roles["viewer"]},
        headers={
            "Authorization": f"Bearer {admin['access_token']}",
            "X-Workspace-ID": ws["id"],
        },
    )
    assert resp.status_code == 200, resp.text

    assert await _wait_for(lambda: _count_eq(admin_me["id"], "member_role_changed", 1))
    row = await _latest_role_change(admin_me["id"])
    assert row.body == "Your role is now viewer."
    assert admin_me["display_name"] not in row.body


async def test_transfer_ownership_notifies_both_users(app_client):
    from tests.conftest import create_workspace, register_user

    owner = await register_user(app_client, "owner@wf-transfer.com")
    heir = await register_user(app_client, "heir@wf-transfer.com")
    owner_me = await _me(app_client, owner)
    heir_me = await _me(app_client, heir)
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    invite = await _invite(app_client, owner, ws["id"], roles["admin"], "heir@wf-transfer.com")
    await _accept(app_client, heir, invite["token"])

    heir_row = next(
        m
        for m in await _members(app_client, owner, ws["id"])
        if m["email"] == "heir@wf-transfer.com"
    )
    resp = await app_client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": heir_row["membership_id"]},
        headers={"Authorization": f"Bearer {owner['access_token']}", "X-Workspace-ID": ws["id"]},
    )
    assert resp.status_code == 200, resp.text

    await _wait_for_count(heir_me["id"], "member_role_changed", 1)
    await _wait_for_count(owner_me["id"], "member_role_changed", 1)

    async def _roles(user_id: str) -> tuple:
        async with SessionFactory() as session:
            result = await session.execute(
                select(Notification)
                .where(
                    Notification.user_id == user_id,
                    Notification.type == "member_role_changed",
                )
                .order_by(Notification.created_at.desc())
            )
            row = result.scalars().first()
        return (row.payload["from_role"], row.payload["to_role"])

    assert await _roles(heir_me["id"]) == ("admin", "owner")
    assert await _roles(owner_me["id"]) == ("owner", "admin")

    # The demoted owner is the actor: told they transferred, not that they
    # changed their own role.
    owner_row = await _latest_role_change(owner_me["id"])
    assert owner_row.body == "You transferred ownership. Your role is now admin."
    assert owner_me["display_name"] not in owner_row.body
    # The heir was changed by someone else, so the name still shows.
    heir_row = await _latest_role_change(heir_me["id"])
    assert heir_row.body.endswith("changed your role from admin to owner.")
    assert owner_me["display_name"] in heir_row.body


async def test_role_changed_body_never_names_an_unknown_role():
    """A null role must not render as a role name, nor as None.

    Driven through the handler directly. WorkspaceMember.role_id has no
    foreign key, so session.get(Role, member.role_id) can return None and a
    publisher emits a null from_role; only a synthetic payload reaches the
    null to_role branch.
    """
    from src.events.bus import EventMetadata
    from src.events.subjects import Subjects
    from src.workflows import build_workflows

    class _CaptureRegistry:
        def __init__(self) -> None:
            self.handlers: dict[str, object] = {}

        def register(self, subject, handler, *, fanout: bool = False) -> None:
            self.handlers[subject] = handler

    registry = _CaptureRegistry()
    build_workflows(registry, None, None)
    handler = registry.handlers[Subjects.WORKSPACE_MEMBER_ROLE_CHANGED]

    async def _emit(*, self_change: bool = False, **roles) -> str:
        # A fresh user per case: two rows created in the same tick have no
        # reliable created_at order.
        user_id = str(uuid.uuid4())
        await handler(
            {
                "workspace_id": str(uuid.uuid4()),
                "workspace_name": "Acme Corp",
                "user_id": user_id,
                "changed_by_user_id": user_id if self_change else str(uuid.uuid4()),
                "changed_by_name": "Test U.",
                **roles,
            },
            EventMetadata(subject=Subjects.WORKSPACE_MEMBER_ROLE_CHANGED),
        )
        return (await _latest_role_change(user_id)).body

    # A null from_role has no role name to print: say there was one.
    assert await _emit(from_role=None, to_role="owner") == (
        "Test U. changed your role from a previous role to owner."
    )
    # A null to_role names no destination, so the clause is dropped rather
    # than filled with a placeholder that reads like a role.
    assert await _emit(from_role="editor", to_role=None) == "Test U. changed your role."
    # The member is the actor: nobody is named, and the two preserved
    # wordings and the null-to_role wording are locked together.
    assert await _emit(self_change=True, from_role="editor", to_role="viewer") == (
        "Your role is now viewer."
    )
    assert await _emit(self_change=True, from_role="owner", to_role="admin") == (
        "You transferred ownership. Your role is now admin."
    )
    assert await _emit(self_change=True, from_role="owner", to_role=None) == (
        "You transferred ownership."
    )
    assert await _emit(self_change=True, from_role="editor", to_role=None) == (
        "Your role was changed."
    )


async def test_role_changed_from_legacy_owner_names_the_transfer():
    """A self-change from the case-variant `Owner` row is still a transfer (#593).

    `set_member_role` refuses to touch the owner role, so a self-change from a
    role named `Owner` is a transfer the same way a self-change from `owner` is.
    """
    from src.events.bus import EventMetadata
    from src.events.subjects import Subjects
    from src.workflows import build_workflows

    class _CaptureRegistry:
        def __init__(self) -> None:
            self.handlers: dict[str, object] = {}

        def register(self, subject, handler, *, fanout: bool = False) -> None:
            self.handlers[subject] = handler

    registry = _CaptureRegistry()
    build_workflows(registry, None, None)
    user_id = str(uuid.uuid4())
    await registry.handlers[Subjects.WORKSPACE_MEMBER_ROLE_CHANGED](
        {
            "workspace_id": str(uuid.uuid4()),
            "workspace_name": "Acme Corp",
            "user_id": user_id,
            "from_role": "Owner",
            "to_role": "admin",
            "changed_by_user_id": user_id,
            "changed_by_name": "Test U.",
        },
        EventMetadata(subject=Subjects.WORKSPACE_MEMBER_ROLE_CHANGED),
    )

    row = await _latest_role_change(user_id)
    assert row.body == "You transferred ownership. Your role is now admin."


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


async def test_unregistered_invite_emails_accept_link(app_client, monkeypatch):
    """The invitation workflow emails unregistered recipients an accept link
    built from the committed row's token, and stays silent for registered ones.
    """
    import src.email.factory as email_factory
    from tests.conftest import create_workspace, register_user

    captured: list = []

    async def _capture(message):
        captured.append(message)
        return True

    monkeypatch.setattr(email_factory, "send_email", _capture)

    # Registering sends a verification email, so scope assertions per recipient.
    def sent_to(address: str) -> list:
        return [m for m in captured if m.to == address]

    owner = await register_user(app_client, "owner@wf5.com")
    ws = await create_workspace(app_client, owner)
    roles = await _roles_by_name(app_client, owner, ws["id"])

    invite = await _invite(app_client, owner, ws["id"], roles["editor"], "stranger@wf5.com")
    assert await _wait_for(lambda: len(sent_to("stranger@wf5.com")) == 1)
    link = f"/invitations/accept?token={invite['token']}"
    assert link in sent_to("stranger@wf5.com")[0].text_body
    assert link in sent_to("stranger@wf5.com")[0].html_body

    member = await register_user(app_client, "member@wf5.com")
    member_me = await _me(app_client, member)
    captured.clear()  # drop the registration verification email
    await _invite(app_client, owner, ws["id"], roles["editor"], "member@wf5.com")
    # The in-app notification proves the event was delivered; the handler returns
    # early for registered recipients, so no email follows.
    await _wait_for_count(member_me["id"], "workspace_invitation", 1)
    await asyncio.sleep(0.1)
    assert sent_to("member@wf5.com") == []


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
