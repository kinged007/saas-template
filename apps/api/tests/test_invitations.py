import asyncio  # noqa: E402

import pytest

import src.core.permissions as perms
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)


async def _wait_for_notifications(
    client, headers, expected: int = 1, deadline_seconds: float = 5.0
) -> list:
    """Poll for the notification rows — the in-process bus delivers
    asynchronously, so a single immediate read can race the workflow."""
    deadline = asyncio.get_running_loop().time() + deadline_seconds
    while True:
        resp = await client.get("/api/v1/notifications", headers=headers)
        assert resp.status_code == 200, resp.text
        items = resp.json()
        if len(items) >= expected:
            return items
        if asyncio.get_running_loop().time() >= deadline:
            return items
        await asyncio.sleep(0.05)


async def test_invite_creates_notification_for_existing_user(app_client):
    client = app_client
    owner = await register_user(client, "kim@example.com")
    ws = await create_workspace(client, owner)

    invitee = await register_user(client, "leo@example.com")
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    editor = next(r for r in roles.json() if r["name"] == "editor")

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "leo@example.com", "role_id": editor["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    invite = resp.json()
    assert invite["status"] == "pending"

    # The notification workflow persisted a notification for the invitee
    # (in-process bus: publish → subscriber → row insert + fanout).
    items = await _wait_for_notifications(client, ws_headers(invitee, ws["id"]))
    assert len(items) == 1
    assert items[0]["type"] == "workspace_invitation"
    assert items[0]["acknowledged"] is False
    assert items[0]["workspace_id"] == ws["id"]
    assert items[0]["workspace_name"] == "Acme Corp"
    assert items[0]["payload"]["workspace_name"] == "Acme Corp"
    # NotificationCenter renders the "Open" button off payload.url; without it
    # the invite is a dead end in the bell.
    assert items[0]["payload"]["url"] == "/invitations"

    # invitee accepts → becomes member with editor role
    accepted = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(invitee),
    )
    assert accepted.status_code == 200, accepted.text

    members = await client.get("/api/v1/members", headers=ws_headers(owner, ws["id"]))
    emails = {m["email"]: m["role"] for m in members.json()}
    assert emails["leo@example.com"] == "editor"


async def test_invite_to_new_user_then_accept(app_client):
    client = app_client
    owner = await register_user(client, "mia@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "newbie@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    invite = resp.json()

    # new user registers, then accepts
    newbie = await register_user(client, "newbie@example.com")
    accepted = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(newbie),
    )
    assert accepted.status_code == 200

    me = await client.get("/api/v1/auth/me", headers=auth_headers(newbie))
    assert me.json()["workspaces"][0]["role"] == "viewer"


async def test_owner_can_change_member_role(app_client):
    client = app_client
    owner = await register_user(client, "nick@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    editor = next(r for r in roles.json() if r["name"] == "editor")
    admin = next(r for r in roles.json() if r["name"] == "admin")

    member = await register_user(client, "oak@example.com")
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "oak@example.com", "role_id": editor["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    invite = resp.json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member),
    )

    members = await client.get("/api/v1/members", headers=ws_headers(owner, ws["id"]))
    membership = next(m for m in members.json() if m["email"] == "oak@example.com")

    resp = await client.patch(
        f"/api/v1/members/{membership['membership_id']}",
        json={"role_id": admin["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 200

    members = await client.get("/api/v1/members", headers=ws_headers(owner, ws["id"]))
    assert next(m for m in members.json() if m["email"] == "oak@example.com")["role"] == "admin"


async def test_invite_to_owner_role_rejected(app_client):
    client = app_client
    owner = await register_user(client, "ray@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    owner_role = next(r for r in roles.json() if r["name"] == "owner")

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "someone@example.com", "role_id": owner_role["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 409
    assert "owner" in resp.json()["detail"]


async def test_my_invitations_lists_received_with_workspace_and_inviter(app_client):
    client = app_client
    owner = await register_user(client, "sam@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    editor = next(r for r in roles.json() if r["name"] == "editor")

    invitee = await register_user(client, "tina@example.com")
    await client.post(
        "/api/v1/invitations",
        json={"email": "tina@example.com", "role_id": editor["id"]},
        headers=ws_headers(owner, ws["id"]),
    )

    resp = await client.get("/api/v1/invitations/mine", headers=auth_headers(invitee))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) == 1
    item = items[0]
    assert item["workspace_name"] == "Acme Corp"
    assert item["invited_by_name"] == "Test U."
    assert item["status"] == "pending"
    assert item["expired"] is False

    # The workspace-scoped list is not reachable without the workspace header.
    resp = await client.get("/api/v1/invitations", headers=auth_headers(invitee))
    assert resp.status_code == 400


async def test_decline_invitation(app_client):
    client = app_client
    owner = await register_user(client, "uma2@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")

    invitee = await register_user(client, "vera@example.com")
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "vera@example.com", "role_id": viewer["id"]},
            headers=ws_headers(owner, ws["id"]),
        )
    ).json()

    resp = await client.post(
        f"/api/v1/invitations/{invite['id']}/decline",
        headers=auth_headers(invitee),
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "declined"

    mine = await client.get("/api/v1/invitations/mine", headers=auth_headers(invitee))
    assert mine.json()[0]["status"] == "declined"

    # Declining again is rejected.
    resp = await client.post(
        f"/api/v1/invitations/{invite['id']}/decline",
        headers=auth_headers(invitee),
    )
    assert resp.status_code == 409

    # Another user cannot decline someone else's invitation.
    other = await register_user(client, "wendy@example.com")
    resp = await client.post(
        f"/api/v1/invitations/{invite['id']}/decline",
        headers=auth_headers(other),
    )
    assert resp.status_code == 404


async def test_expired_invitation_shows_expired_and_rejects_accept(app_client):
    client = app_client
    owner = await register_user(client, "xander@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")

    invitee = await register_user(client, "yara@example.com")
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "yara@example.com", "role_id": viewer["id"]},
            headers=ws_headers(owner, ws["id"]),
        )
    ).json()

    # Backdate the expiry.
    from datetime import timedelta

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.models.core import Invitation

    async with SessionFactory() as session:
        row = await session.get(Invitation, invite["id"])
        row.expires_at = now_utc() - timedelta(minutes=5)
        await session.commit()

    mine = await client.get("/api/v1/invitations/mine", headers=auth_headers(invitee))
    item = mine.json()[0]
    assert item["status"] == "pending"
    assert item["expired"] is True

    resp = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(invitee),
    )
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"]

    # The failed accept already flipped the invitation to revoked.
    mine = await client.get("/api/v1/invitations/mine", headers=auth_headers(invitee))
    assert mine.json()[0]["status"] == "revoked"

    resp = await client.post(
        f"/api/v1/invitations/{invite['id']}/decline",
        headers=auth_headers(invitee),
    )
    assert resp.status_code == 409


async def test_notification_read_all(app_client):
    client = app_client
    owner = await register_user(client, "tess@example.com")
    ws = await create_workspace(client, owner)
    invitee = await register_user(client, "ursula@example.com")
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    await client.post(
        "/api/v1/invitations",
        json={"email": "ursula@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    await _wait_for_notifications(client, ws_headers(invitee, ws["id"]))

    resp = await client.patch(
        "/api/v1/notifications/read-all", headers=ws_headers(invitee, ws["id"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["acknowledged"] == 1

    notes = await client.get(
        "/api/v1/notifications?acknowledged=false", headers=ws_headers(invitee, ws["id"])
    )
    assert notes.json() == []

    # idempotent — second call acknowledges nothing
    resp = await client.patch(
        "/api/v1/notifications/read-all", headers=ws_headers(invitee, ws["id"])
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] == 0


async def test_notification_acknowledge_persists(app_client):
    client = app_client
    owner = await register_user(client, "pam@example.com")
    ws = await create_workspace(client, owner)
    invitee = await register_user(client, "quin@example.com")
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    await client.post(
        "/api/v1/invitations",
        json={"email": "quin@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )

    notes = await _wait_for_notifications(client, ws_headers(invitee, ws["id"]))
    nid = notes[0]["id"]

    resp = await client.patch(
        f"/api/v1/notifications/{nid}",
        json={"acknowledged": True},
        headers=ws_headers(invitee, ws["id"]),
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is True

    # persisted — still acknowledged after re-fetch
    notes = await client.get("/api/v1/notifications", headers=ws_headers(invitee, ws["id"]))
    assert notes.json()[0]["acknowledged"] is True


async def test_notification_unacknowledge_and_filter(app_client):
    client = app_client
    owner = await register_user(client, "robin@example.com")
    ws = await create_workspace(client, owner)
    invitee = await register_user(client, "sue@example.com")
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    await client.post(
        "/api/v1/invitations",
        json={"email": "sue@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )

    headers = ws_headers(invitee, ws["id"])
    notes = await _wait_for_notifications(client, headers)
    nid = notes[0]["id"]

    # mark read, then back to unread
    await client.patch(f"/api/v1/notifications/{nid}", json={"acknowledged": True}, headers=headers)
    resp = await client.patch(
        f"/api/v1/notifications/{nid}", json={"acknowledged": False}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["acknowledged"] is False

    # bare `acknowledged=false` filter (simple-rest flat style) → unread only
    resp = await client.get("/api/v1/notifications?acknowledged=false", headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["acknowledged"] is False

    # legacy `filter[acknowledged]=true` style → read only
    await client.patch(f"/api/v1/notifications/{nid}", json={"acknowledged": True}, headers=headers)
    resp = await client.get(
        "/api/v1/notifications?filter[acknowledged]=true", headers=ws_headers(invitee, ws["id"])
    )
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["acknowledged"] is True


async def test_list_invitations_pagination(app_client):
    client = app_client
    owner = await register_user(client, "inv_page_owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    roles = await client.get("/api/v1/roles", headers=owner_headers)
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    for i in range(3):
        resp = await client.post(
            "/api/v1/invitations",
            json={"email": f"inv_page_{i}@example.com", "role_id": viewer["id"]},
            headers=owner_headers,
        )
        assert resp.status_code == 201, resp.text

    resp = await client.get("/api/v1/invitations?limit=2&offset=0", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 2

    resp = await client.get("/api/v1/invitations?limit=2&offset=2", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 1
    assert resp.json()[0]["email"] == "inv_page_2@example.com"

    resp = await client.get("/api/v1/invitations?_start=2&_end=4", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 1
    assert resp.json()[0]["email"] == "inv_page_2@example.com"


async def test_resend_invitation_requires_a_manager_actor(app_client):
    """#302: resend is a manager action. A viewer actor must be refused, and
    the actor may not be left out — an omitted actor skipped authorization."""
    from src.db.session import SessionFactory
    from src.models.workspace import User
    from src.services.workspaces import WorkspaceForbidden, WorkspaceService

    client = app_client
    owner = await register_user(client, "resend-owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    viewer = next(
        r
        for r in (await client.get("/api/v1/roles", headers=owner_headers)).json()
        if r["name"] == "viewer"
    )

    viewer_invite = await client.post(
        "/api/v1/invitations",
        json={"email": "resend-viewer@example.com", "role_id": viewer["id"]},
        headers=owner_headers,
    )
    assert viewer_invite.status_code == 201, viewer_invite.text
    viewer_tokens = await register_user(client, "resend-viewer@example.com")
    accepted = await client.post(
        "/api/v1/invitations/accept",
        params={"token": viewer_invite.json()["token"]},
        headers=auth_headers(viewer_tokens),
    )
    assert accepted.status_code == 200, accepted.text
    viewer_id = (await client.get("/api/v1/auth/me", headers=auth_headers(viewer_tokens))).json()[
        "id"
    ]
    owner_id = (await client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()["id"]

    target = await client.post(
        "/api/v1/invitations",
        json={"email": "resend-target@example.com", "role_id": viewer["id"]},
        headers=owner_headers,
    )
    assert target.status_code == 201, target.text

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        viewer_user = await session.get(User, viewer_id)
        assert viewer_user is not None
        with pytest.raises(WorkspaceForbidden):
            await service.resend_invitation(ws["id"], target.json()["id"], actor=viewer_user)
        with pytest.raises(TypeError):
            await service.resend_invitation(ws["id"], target.json()["id"])
        resent = await service.resend_invitation(
            ws["id"], target.json()["id"], actor=await session.get(User, owner_id)
        )
        assert resent.status == "pending"


async def test_resend_invitation_route_403s_a_non_manager_recruiter(app_client):
    """The route guard is a role check, so a `member:create` recruiter is refused
    with 403 (not 404) even for an id that does not exist — the guard runs before
    the lookup, so the response is not an existence oracle."""
    client = app_client
    owner = await register_user(client, "recruiter-owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    role = await client.post(
        "/api/v1/roles",
        json={"name": "invite-op", "permissions": [perms.MEMBER_CREATE]},
        headers=owner_headers,
    )
    assert role.status_code == 201, role.text
    role_id = role.json()["id"]

    recruiter_invite = await client.post(
        "/api/v1/invitations",
        json={"email": "recruiter@example.com", "role_id": role_id},
        headers=owner_headers,
    )
    assert recruiter_invite.status_code == 201, recruiter_invite.text
    recruiter = await register_user(client, "recruiter@example.com")
    accepted = await client.post(
        "/api/v1/invitations/accept",
        params={"token": recruiter_invite.json()["token"]},
        headers=auth_headers(recruiter),
    )
    assert accepted.status_code == 200, accepted.text
    recruiter_headers = ws_headers(recruiter, ws["id"])

    # the recruiter can still create invites: the denial is role-scoped
    recruiter_target = await client.post(
        "/api/v1/invitations",
        json={"email": "recruiter-target@example.com", "role_id": role_id},
        headers=recruiter_headers,
    )
    assert recruiter_target.status_code == 201, recruiter_target.text

    for invitation_id in (recruiter_target.json()["id"], "does-not-exist"):
        resp = await client.post(
            f"/api/v1/invitations/{invitation_id}/resend", headers=recruiter_headers
        )
        assert resp.status_code == 403, (invitation_id, resp.status_code, resp.text)


async def test_revoke_invitation_route_403s_a_non_manager(app_client):
    """`revoke_invitation` carries the same owner/admin guard as `resend_invitation`."""
    client = app_client
    owner = await register_user(client, "revoke-owner@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    viewer = next(
        r
        for r in (await client.get("/api/v1/roles", headers=owner_headers)).json()
        if r["name"] == "viewer"
    )

    viewer_invite = await client.post(
        "/api/v1/invitations",
        json={"email": "revoke-viewer@example.com", "role_id": viewer["id"]},
        headers=owner_headers,
    )
    assert viewer_invite.status_code == 201, viewer_invite.text
    viewer_tokens = await register_user(client, "revoke-viewer@example.com")
    accepted = await client.post(
        "/api/v1/invitations/accept",
        params={"token": viewer_invite.json()["token"]},
        headers=auth_headers(viewer_tokens),
    )
    assert accepted.status_code == 200, accepted.text
    viewer_headers = ws_headers(viewer_tokens, ws["id"])

    target = await client.post(
        "/api/v1/invitations",
        json={"email": "revoke-target@example.com", "role_id": viewer["id"]},
        headers=owner_headers,
    )
    assert target.status_code == 201, target.text

    resp = await client.delete(f"/api/v1/invitations/{target.json()['id']}", headers=viewer_headers)
    assert resp.status_code == 403, (resp.status_code, resp.text)

    ok = await client.delete(f"/api/v1/invitations/{target.json()['id']}", headers=owner_headers)
    assert ok.status_code == 204, (ok.status_code, ok.text)
