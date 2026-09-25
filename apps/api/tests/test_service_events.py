"""Unit tests for service → event-bus publishing.

These tests wire each service to a RecordingBus and assert the exact
subjects, payloads and audit events the service emits — without touching
NATS or the in-process delivery machinery.
"""

from __future__ import annotations

import pytest

from src.db.session import SessionFactory
from src.events.subjects import Subjects
from src.services.api_keys import ApiKeyService
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService
from tests.bus_doubles import RecordingBus


class FailingBus(RecordingBus):
    async def publish(self, *args, **kwargs):
        raise RuntimeError("publish failed")


@pytest.fixture
async def bus():
    return RecordingBus()


async def _register(bus, email, display_name, *, ip_address=None):
    # display_name arg is legacy — split into first/last for new API
    parts = display_name.strip().split()
    fn = parts[0] if parts else "Test"
    ln = " ".join(parts[1:]) if len(parts) > 1 else None
    async with SessionFactory() as session:
        return await AuthService(session, bus).register(
            email=email, password="Password123!", first_name=fn, last_name=ln, ip_address=ip_address
        )


async def _get_user(bus, user_id):
    async with SessionFactory() as session:
        return await AuthService(session, bus).get_user(user_id)


async def _create_workspace(bus, owner_id, *, slug, name="Acme Corp"):
    async with SessionFactory() as session:
        return await WorkspaceService(session, bus).create_workspace(
            name=name,
            slug=slug,
            description=None,
            owner=await AuthService(session, bus).get_user(owner_id),
        )


async def _invite_member(bus, owner_id, workspace, email, role_name="editor"):
    async with SessionFactory() as session:
        service = WorkspaceService(session, bus)
        role = await service._role_by_name(workspace.id, role_name)
        return await service.create_invitation(
            workspace=workspace,
            email=email,
            role=role,
            invited_by=await AuthService(session, bus).get_user(owner_id),
        )


async def _accept_invitation(bus, token, invitee):
    async with SessionFactory() as session:
        await WorkspaceService(session, bus).accept_invitation(token, invitee)


@pytest.fixture
async def owner(bus):
    user = await _register(bus, "owner@example.com", "Owner", ip_address="127.0.0.1")
    bus.events.clear()  # ignore the registration audit event
    return user


# --------------------------------------------------------------------- auth


async def test_register_emits_user_audit(bus):
    user = await _register(bus, "owner@example.com", "Owner", ip_address="10.0.0.1")
    assert bus.actions() == ["user.register"]
    payload = bus.audit()[0][0]
    assert payload["workspace_id"] is None
    assert payload["resource_type"] == "user"
    assert payload["resource_id"] == user.id
    assert payload["actor_user_id"] == user.id
    assert payload["ip_address"] == "10.0.0.1"
    assert payload["details"]["email"] == "owner@example.com"


async def test_login_emits_user_audit(bus):
    await _register(bus, "owner@example.com", "Owner")
    bus.events.clear()
    async with SessionFactory() as session:
        await AuthService(session, bus).login_password("owner@example.com", "Password123!")
    assert bus.actions() == ["user.login"]
    payload = bus.audit()[0][0]
    assert payload["workspace_id"] is None
    assert payload["actor_user_id"] is not None


async def test_logout_emits_user_audit(bus):
    await _register(bus, "owner@example.com", "Owner")
    bus.events.clear()
    async with SessionFactory() as session:
        service = AuthService(session, bus)
        user = await service.login_password("owner@example.com", "Password123!")
        pair = await service.issue_tokens(user)
        await service.revoke_refresh(pair.refresh_token)
    assert bus.actions() == ["user.login", "user.logout"]


# --------------------------------------------------------------- workspaces


async def test_workspace_create_emits_event_and_audit(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme")

    created = bus.by_subject(Subjects.WORKSPACE_CREATED)
    assert len(created) == 1
    payload = created[0][0]
    assert payload["workspace_id"] == workspace.id
    assert payload["name"] == "Acme Corp"
    assert payload["created_by_user_id"] == owner.id

    assert bus.actions() == ["workspace.created"]
    audit = bus.audit()[0][0]
    assert audit["workspace_id"] == workspace.id
    assert audit["resource_type"] == "workspace"
    assert audit["actor_user_id"] == owner.id


async def test_workspace_update_emits_audit_only_when_changed(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme-upd")
    bus.events.clear()
    async with SessionFactory() as session:
        service = WorkspaceService(session, bus)
        await service.update_workspace(
            workspace.id, name="Acme Renamed", actor=owner, ip_address="10.0.0.1"
        )
    assert bus.actions() == ["workspace.updated"]
    assert bus.by_subject(Subjects.WORKSPACE_CREATED) == []
    audit = bus.audit()[0][0]
    assert audit["details"]["name"] == {"from": "Acme Corp", "to": "Acme Renamed"}

    bus.events.clear()
    async with SessionFactory() as session:
        service = WorkspaceService(session, bus)
        await service.update_workspace(workspace.id, name="Acme Renamed", actor=owner)
    assert bus.events == []  # no change → no event


async def test_workspace_delete_emits_audit(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme-del")
    bus.events.clear()
    async with SessionFactory() as session:
        await WorkspaceService(session, bus).delete_workspace(workspace.id, actor=owner)
    assert bus.actions() == ["workspace.deleted"]
    assert bus.audit()[0][0]["resource_id"] == workspace.id


# --------------------------------------------------------------- invitations


async def test_invitation_to_registered_user_emits_two_events_and_audit(bus, owner):
    invitee = await _register(bus, "member@example.com", "Member")
    workspace = await _create_workspace(bus, owner.id, slug="acme2")
    bus.events.clear()
    await _invite_member(bus, owner.id, workspace, "member@example.com")

    invitation = bus.by_subject(Subjects.WORKSPACE_INVITATION_CREATED)
    assert len(invitation) == 1
    inv = invitation[0][0]
    assert inv["workspace_id"] == workspace.id
    assert inv["email"] == "member@example.com"
    assert inv["role"] == "editor"
    assert inv["is_registered"] is True
    assert inv["invited_by_user_id"] == owner.id

    member_invited = bus.by_subject(Subjects.WORKSPACE_MEMBER_INVITED)
    assert len(member_invited) == 1
    assert member_invited[0][0]["user_id"] == invitee.id
    assert member_invited[0][0]["workspace_id"] == workspace.id

    assert bus.actions() == ["invitation.created"]
    audit = bus.audit()[-1][0]
    assert audit["workspace_id"] == workspace.id
    assert audit["details"]["email"] == "member@example.com"


async def test_invitation_to_unregistered_email_emits_invitation_event_only(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme3")
    bus.events.clear()
    await _invite_member(bus, owner.id, workspace, "stranger@example.com")

    invitation = bus.by_subject(Subjects.WORKSPACE_INVITATION_CREATED)
    assert len(invitation) == 1
    assert invitation[0][0]["is_registered"] is False
    # No in-app notification for unregistered recipients — email hook instead.
    assert bus.by_subject(Subjects.WORKSPACE_MEMBER_INVITED) == []


async def test_accept_invitation_emits_member_joined(bus, owner):
    invitee = await _register(bus, "member@example.com", "Member")
    workspace = await _create_workspace(bus, owner.id, slug="acme4")
    invite = await _invite_member(bus, owner.id, workspace, "member@example.com")
    bus.events.clear()
    await _accept_invitation(bus, invite.token, invitee)

    joined = bus.by_subject(Subjects.WORKSPACE_MEMBER_JOINED)
    assert len(joined) == 1
    payload = joined[0][0]
    assert payload["user_id"] == invitee.id
    assert payload["workspace_id"] == workspace.id
    assert payload["workspace_name"] == "Acme Corp"
    assert payload["invited_by_user_id"] == owner.id
    assert payload["user_name"] == "Member"

    assert bus.actions() == ["invitation.accepted"]
    assert bus.audit()[0][0]["actor_user_id"] == invitee.id


async def test_decline_invitation_emits_audit(bus, owner):
    invitee = await _register(bus, "member@example.com", "Member")
    workspace = await _create_workspace(bus, owner.id, slug="acme-decl")
    invite = await _invite_member(bus, owner.id, workspace, "member@example.com")
    bus.events.clear()
    async with SessionFactory() as session:
        await WorkspaceService(session, bus).decline_invitation(invite.id, invitee)
    assert bus.actions() == ["invitation.declined"]


async def test_revoke_invitation_emits_audit(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme-rev")
    invite = await _invite_member(bus, owner.id, workspace, "stranger@example.com")
    bus.events.clear()
    async with SessionFactory() as session:
        await WorkspaceService(session, bus).revoke_invitation(workspace.id, invite.id, actor=owner)
    assert bus.actions() == ["invitation.revoked"]
    assert bus.audit()[0][0]["actor_user_id"] == owner.id


# ------------------------------------------------------------------ members


async def test_role_change_emits_event_and_audit(bus, owner):
    invitee = await _register(bus, "member@example.com", "Member")
    workspace = await _create_workspace(bus, owner.id, slug="acme5")
    invite = await _invite_member(bus, owner.id, workspace, "member@example.com")
    await _accept_invitation(bus, invite.token, invitee)
    bus.events.clear()

    async with SessionFactory() as session:
        service = WorkspaceService(session, bus)
        member = (await service.list_members(workspace.id))[1][0]
        new_role = await service._role_by_name(workspace.id, "viewer")
        await service.set_member_role(
            workspace.id, member.id, new_role.id, actor=owner, ip_address="10.0.0.1"
        )

    changed = bus.by_subject(Subjects.WORKSPACE_MEMBER_ROLE_CHANGED)
    assert len(changed) == 1
    payload = changed[0][0]
    assert payload["user_id"] == invitee.id
    assert payload["from_role"] == "editor"
    assert payload["to_role"] == "viewer"
    assert payload["changed_by_user_id"] == owner.id

    assert bus.actions() == ["member.role_changed"]
    audit = bus.audit()[0][0]
    assert audit["resource_type"] == "member"
    assert audit["actor_user_id"] == owner.id
    assert audit["details"]["from_role"] == "editor"
    assert audit["details"]["to_role"] == "viewer"


async def test_leave_survives_event_publish_failure(bus, owner):
    invitee = await _register(bus, "leave-failure@example.com", "Member")
    workspace = await _create_workspace(bus, owner.id, slug="leave-failure")
    invite = await _invite_member(bus, owner.id, workspace, "leave-failure@example.com")
    await _accept_invitation(bus, invite.token, invitee)

    async with SessionFactory() as session:
        actor = await AuthService(session).get_user(invitee.id)
        await WorkspaceService(session, FailingBus()).leave_workspace(workspace.id, actor=actor)
        assert await WorkspaceService(session).get_membership(workspace.id, invitee.id) is None


async def test_member_removed_emits_event_and_audit(bus, owner):
    invitee = await _register(bus, "member@example.com", "Member")
    workspace = await _create_workspace(bus, owner.id, slug="acme6")
    invite = await _invite_member(bus, owner.id, workspace, "member@example.com")
    await _accept_invitation(bus, invite.token, invitee)
    bus.events.clear()

    async with SessionFactory() as session:
        service = WorkspaceService(session, bus)
        member = (await service.list_members(workspace.id))[1][0]
        await service.remove_member(workspace.id, member.id, actor=owner, ip_address="10.0.0.1")

    removed = bus.by_subject(Subjects.WORKSPACE_MEMBER_REMOVED)
    assert len(removed) == 1
    payload = removed[0][0]
    assert payload["user_id"] == invitee.id
    assert payload["workspace_id"] == workspace.id
    assert payload["removed_by_user_id"] == owner.id

    assert bus.actions() == ["member.removed"]
    assert bus.audit()[0][0]["actor_user_id"] == owner.id


# ----------------------------------------------------------------- api keys


async def test_api_key_create_and_revoke_emit_events_and_audit(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme7")
    async with SessionFactory() as session:
        key, raw = await ApiKeyService(session, bus).create_api_key(
            workspace_id=workspace.id,
            name="ci-key",
            permissions=["workspace:read"],
            actor=owner,
            ip_address="10.0.0.1",
        )

    created = bus.by_subject(Subjects.APIKEY_CREATED)
    assert len(created) == 1
    payload = created[0][0]
    assert payload["apikey_id"] == key.id
    assert payload["workspace_id"] == workspace.id
    assert payload["name"] == "ci-key"
    assert payload["created_by_user_id"] == owner.id
    # The raw secret must never leave the service.
    assert raw not in str(bus.events)

    assert bus.actions()[-1] == "apikey.created"
    audit = bus.audit()[-1][0]
    assert audit["resource_type"] == "apikey"
    assert audit["ip_address"] == "10.0.0.1"

    async with SessionFactory() as session:
        await ApiKeyService(session, bus).revoke_api_key(workspace.id, key.id, actor=owner)

    revoked = bus.by_subject(Subjects.APIKEY_REVOKED)
    assert len(revoked) == 1
    assert revoked[0][0]["apikey_id"] == key.id
    assert revoked[0][0]["revoked_by_user_id"] == owner.id
    assert bus.actions()[-1] == "apikey.revoked"

    async with SessionFactory() as session:
        await ApiKeyService(session, bus).set_quota(
            workspace.id, key.id, 5, actor=owner, ip_address="10.0.0.1"
        )

    updated = bus.by_subject(Subjects.APIKEY_UPDATED)
    assert len(updated) == 1
    assert updated[0][0]["apikey_id"] == key.id
    assert updated[0][0]["usage_quota"] == 5
    assert updated[0][0]["updated_by_user_id"] == owner.id
    assert bus.actions()[-1] == "apikey.updated"
    audit = bus.audit()[-1][0]
    assert audit["resource_type"] == "apikey"
    assert audit["ip_address"] == "10.0.0.1"


# ------------------------------------------------------------------- roles


async def test_custom_role_create_emits_audit(bus, owner):
    workspace = await _create_workspace(bus, owner.id, slug="acme8")
    bus.events.clear()
    async with SessionFactory() as session:
        await WorkspaceService(session, bus).create_custom_role(
            workspace.id,
            name="billing",
            description="billing admin",
            permissions=["audit:read"],
            actor=owner,
            ip_address="10.0.0.1",
        )
    assert bus.actions() == ["role.created"]
    audit = bus.audit()[0][0]
    assert audit["workspace_id"] == workspace.id
    assert audit["resource_type"] == "role"
    assert audit["details"]["name"] == "billing"


# -------------------------------------------------------------- no bus wired


async def test_services_without_bus_are_noops():
    """publish_audit/publish_event must no-op when no bus is wired."""
    async with SessionFactory() as session:
        user = await AuthService(session).register(
            email="nobus@example.com", password="Password123!", first_name="No", last_name="Bus"
        )
        service = WorkspaceService(session)
        workspace = await service.create_workspace(
            name="Acme Corp", slug="nobus-ws", description=None, owner=user
        )
        assert workspace.id is not None
