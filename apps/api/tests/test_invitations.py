import asyncio  # noqa: E402

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


async def _wait_for_audit(action: str, workspace_id: str, deadline_seconds: float = 5.0) -> list:
    """Poll audit_log_entries — the in-process bus delivers asynchronously, so
    a single immediate read can race the workflow."""
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.audit import AuditLogEntry

    deadline = asyncio.get_running_loop().time() + deadline_seconds
    while True:
        async with SessionFactory() as session:
            rows = (
                (
                    await session.execute(
                        select(AuditLogEntry).where(
                            AuditLogEntry.action == action,
                            AuditLogEntry.workspace_id == workspace_id,
                        )
                    )
                )
                .scalars()
                .all()
            )
            if rows:
                return list(rows)
        if asyncio.get_running_loop().time() >= deadline:
            return []
        await asyncio.sleep(0.05)


async def _wait_for(predicate, deadline_seconds: float = 5.0) -> bool:
    """Poll a synchronous predicate until it holds."""
    deadline = asyncio.get_running_loop().time() + deadline_seconds
    while not predicate():
        if asyncio.get_running_loop().time() >= deadline:
            return False
        await asyncio.sleep(0.05)
    return True


async def test_failed_invitation_email_is_recorded_in_audit(app_client, monkeypatch):
    from src.db.session import SessionFactory
    from src.models.core import Invitation

    async def failing_send(message):
        return False

    # `send_email` never raises, it returns False — the handler must act on it.
    monkeypatch.setattr("src.email.factory.send_email", failing_send)

    client = app_client
    owner = await register_user(client, "noemail_owner@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    owner_me = (await client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "unreachable@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    invite = resp.json()

    rows = await _wait_for_audit("invitation.email_failed", ws["id"])
    assert len(rows) == 1
    row = rows[0]
    assert row.workspace_id == ws["id"]
    assert row.resource_type == "invitation"
    assert row.resource_id == invite["id"]
    assert row.details["email"] == "unreachable@example.com"
    assert row.details["invited_by_user_id"] == owner_me["id"]
    assert row.details["invited_by_name"] == owner_me["display_name"]

    # The invitation row stays pending: the audit entry is the only trace of the
    # failure. `resend` skips a still-pending, unexpired invitation, so the row
    # stays as it is until it is revoked or expires.
    async with SessionFactory() as session:
        assert (await session.get(Invitation, invite["id"])).status == "pending"


async def test_successful_invitation_email_records_no_audit_row(app_client, monkeypatch):
    sent: list = []

    async def spy_send(message):
        sent.append(message)
        return True

    monkeypatch.setattr("src.email.factory.send_email", spy_send)

    client = app_client
    owner = await register_user(client, "okemail_owner@example.com")
    ws = await create_workspace(client, owner)
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")

    resp = await client.post(
        "/api/v1/invitations",
        json={"email": "reachable@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 201, resp.text

    # The send has to have happened, otherwise "no audit row" proves nothing.
    # Registration also sends mail, so match the invitee rather than index 0.
    assert await _wait_for(lambda: any(m.to == "reachable@example.com" for m in sent))
    invites = [m for m in sent if m.to == "reachable@example.com"]
    assert len(invites) == 1
    assert "/invitations/accept?token=" in invites[0].html_body
    assert await _wait_for_audit("invitation.email_failed", ws["id"], deadline_seconds=0.5) == []


async def test_invitation_email_failure_without_invitation_id_is_not_audited(
    app, app_client, monkeypatch
):
    """`resource_id` is NOT NULL, so a payload without an invitation id is
    logged and dropped instead of written as a null row."""
    from src.events.subjects import Subjects

    sent: list = []
    audits: list = []

    async def failing_send(message):
        sent.append(message)
        return False

    async def spy_audit(bus, **kwargs):
        audits.append(kwargs)

    monkeypatch.setattr("src.email.factory.send_email", failing_send)
    monkeypatch.setattr("src.workflows.publish_audit", spy_audit)

    client = app_client
    owner = await register_user(client, "noid_owner@example.com")
    ws = await create_workspace(client, owner)
    owner_me = (await client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()

    await app.state.container.bus.publish(
        Subjects.WORKSPACE_INVITATION_CREATED,
        {
            "workspace_id": ws["id"],
            "workspace_name": ws["name"],
            "email": "noid@example.com",
            "invited_by_user_id": owner_me["id"],
            "invited_by_name": owner_me["display_name"],
            "is_registered": False,
        },
    )

    assert await _wait_for(lambda: any(m.to == "noid@example.com" for m in sent))
    await asyncio.sleep(0.2)  # let the handler get past the guard
    assert audits == []
    assert await _wait_for_audit("invitation.email_failed", ws["id"], deadline_seconds=0.5) == []


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

    # The unsorted list now defaults to `created_at desc, id desc` (#449), so
    # which invitation lands at offset=2 depends on generated ids. Assert the
    # pages are slices of the unpaginated read instead of against insertion
    # order, which the old rowid read happened to reproduce.
    resp = await client.get("/api/v1/invitations?limit=10", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    ordered = resp.json()
    assert len(ordered) == 3

    resp = await client.get("/api/v1/invitations?limit=2&offset=0", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 2
    assert resp.json() == ordered[:2]

    resp = await client.get("/api/v1/invitations?limit=2&offset=2", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 1
    assert resp.json() == ordered[2:]

    resp = await client.get("/api/v1/invitations?_start=2&_end=4", headers=owner_headers)
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 1
    assert resp.json() == ordered[2:]
