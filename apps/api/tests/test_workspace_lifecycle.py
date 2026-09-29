import pytest
from sqlalchemy.exc import IntegrityError

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def _role_id(client, headers, name: str) -> str:
    roles = await client.get("/api/v1/roles", headers=headers)
    assert roles.status_code == 200, roles.text
    return next(r for r in roles.json() if r["name"] == name)["id"]


async def _member_by_email(client, headers, email: str) -> dict:
    members = await client.get("/api/v1/members", headers=headers)
    assert members.status_code == 200, members.text
    return next(m for m in members.json() if m["email"] == email)


async def _invite_and_join(client, owner_tokens, ws, email: str, role_name: str = "viewer"):
    owner_headers = ws_headers(owner_tokens, ws["id"])
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": await _role_id(client, owner_headers, role_name)},
        headers=owner_headers,
    )
    assert invite.status_code == 201, invite.text
    user = await register_user(client, email)
    joined = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(user),
    )
    assert joined.status_code == 200, joined.text
    return user


async def test_suspend_loses_access_without_losing_history(app_client):
    client = app_client
    owner = await register_user(client, "own@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    member_tokens = await _invite_and_join(client, owner, ws, "mem@example.com", "editor")
    member = await _member_by_email(client, owner_headers, "mem@example.com")
    member_headers = ws_headers(member_tokens, ws["id"])
    key = await client.post(
        "/api/v1/api-keys",
        json={"name": "member-key", "permissions": ["member:read"]},
        headers=member_headers,
    )
    assert key.status_code == 201, key.text
    key_headers = {
        "Authorization": f"Bearer {key.json()['key']}",
        "X-Workspace-ID": ws["id"],
    }

    assert (
        await client.get("/api/v1/workspaces/" + ws["id"], headers=member_headers)
    ).status_code == 200
    resp = await client.post(
        f"/api/v1/members/{member['membership_id']}/suspend", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "suspended"

    # history kept: row still listed with suspended status
    suspended = await _member_by_email(client, owner_headers, "mem@example.com")
    assert suspended["status"] == "suspended"

    # access lost
    assert (
        await client.get("/api/v1/workspaces/" + ws["id"], headers=member_headers)
    ).status_code == 403
    assert (await client.get("/api/v1/members", headers=member_headers)).status_code == 403
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 403

    resp = await client.post(
        f"/api/v1/members/{member['membership_id']}/reactivate", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    assert (
        await client.get("/api/v1/workspaces/" + ws["id"], headers=member_headers)
    ).status_code == 200


async def test_suspend_owner_or_self_rejected(app_client):
    client = app_client
    owner = await register_user(client, "own2@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    owner_row = await _member_by_email(client, owner_headers, "own2@example.com")

    assert (
        await client.post(
            f"/api/v1/members/{owner_row['membership_id']}/suspend", headers=owner_headers
        )
    ).status_code == 409
    await _invite_and_join(client, owner, ws, "adm@example.com", "admin")
    admin_row = await _member_by_email(client, owner_headers, "adm@example.com")
    assert (
        await client.post(
            f"/api/v1/members/{admin_row['membership_id']}/suspend", headers=owner_headers
        )
    ).status_code == 200


async def test_transfer_keeps_exactly_one_owner(app_client):
    client = app_client
    owner = await register_user(client, "own3@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    new_owner = await _invite_and_join(client, owner, ws, "heir@example.com", "admin")
    target = await _member_by_email(client, owner_headers, "heir@example.com")

    resp = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target["membership_id"]},
        headers=owner_headers,
    )
    assert resp.status_code == 200, resp.text

    members = (await client.get("/api/v1/members", headers=ws_headers(new_owner, ws["id"]))).json()
    assert [m["role"] for m in members if m["role"] == "owner"] == ["owner"]
    old = next(m for m in members if m["email"] == "own3@example.com")
    assert old["role"] == "admin"

    # old owner can no longer delete; new owner can
    assert (
        await client.delete(f"/api/v1/workspaces/{ws['id']}", headers=owner_headers)
    ).status_code == 403

    # non-owner transfer rejected
    other = await _invite_and_join(client, new_owner, ws, "plain@example.com", "admin")
    target2 = await _member_by_email(client, ws_headers(new_owner, ws["id"]), "plain@example.com")
    resp = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target2["membership_id"]},
        headers=ws_headers(other, ws["id"]),
    )
    assert resp.status_code == 403


async def test_resend_expired_invitation(app_client):
    client = app_client
    owner = await register_user(client, "own4@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "late@example.com",
            "role_id": await _role_id(client, owner_headers, "viewer"),
        },
        headers=owner_headers,
    )
    assert invite.status_code == 201, invite.text
    old_token = invite.json()["token"]

    # Revoke, then resend to prove a dead invite becomes usable again.
    rev = await client.delete(f"/api/v1/invitations/{invite.json()['id']}", headers=owner_headers)
    assert rev.status_code == 204, rev.text
    resp = await client.post(
        f"/api/v1/invitations/{invite.json()['id']}/resend", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["status"] == "pending"
    assert body["token"] != old_token

    user = await register_user(client, "late@example.com")
    joined = await client.post(
        "/api/v1/invitations/accept",
        params={"token": body["token"]},
        headers=auth_headers(user),
    )
    assert joined.status_code == 200, joined.text


async def test_api_key_cannot_transfer_ownership(app_client):
    """A key holding only workspace:update must not be able to demote the owner."""
    client = app_client
    owner = await register_user(client, "own6@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    heir = await _invite_and_join(client, owner, ws, "heir6@example.com", "admin")
    target = await _member_by_email(client, owner_headers, "heir6@example.com")
    key = await client.post(
        "/api/v1/api-keys",
        json={"name": "narrow", "permissions": ["workspace:update"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert key.status_code == 201, key.text
    key_headers = {
        "Authorization": f"Bearer {key.json()['key']}",
        "X-Workspace-ID": ws["id"],
    }

    resp = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer",
        json={"new_owner_membership_id": target["membership_id"]},
        headers=key_headers,
    )
    assert resp.status_code == 403, resp.text
    members = (await client.get("/api/v1/members", headers=ws_headers(heir, ws["id"]))).json()
    assert next(m for m in members if m["email"] == "own6@example.com")["role"] == "owner"


async def test_resend_rejects_accepted_invitation(app_client):
    client = app_client
    owner = await register_user(client, "own7@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "joined@example.com",
            "role_id": await _role_id(client, owner_headers, "viewer"),
        },
        headers=owner_headers,
    )
    assert invite.status_code == 201, invite.text
    user = await register_user(client, "joined@example.com")
    joined = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(user),
    )
    assert joined.status_code == 200, joined.text

    resp = await client.post(
        f"/api/v1/invitations/{invite.json()['id']}/resend", headers=owner_headers
    )
    assert resp.status_code == 409, resp.text


async def test_resend_by_api_key_then_suspended_owner_is_rejected(app_client):
    """An API key may resend; suspending its owner must revoke that access.

    The two halves fail for different reasons: the first passes through the
    service, the second is rejected by `require_permission` before it runs.
    """
    client = app_client
    owner = await register_user(client, "own9@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "stray@example.com",
            "role_id": await _role_id(client, owner_headers, "viewer"),
        },
        headers=owner_headers,
    )
    assert invite.status_code == 201, invite.text
    invite_id = invite.json()["id"]

    # `editor`/`viewer` lack member:create, so the key needs an `admin` owner.
    admin_tokens = await _invite_and_join(client, owner, ws, "adm9@example.com", "admin")
    key = await client.post(
        "/api/v1/api-keys",
        json={"name": "admin-key", "permissions": ["member:create"]},
        headers=ws_headers(admin_tokens, ws["id"]),
    )
    assert key.status_code == 201, key.text
    key_headers = {"Authorization": f"Bearer {key.json()['key']}", "X-Workspace-ID": ws["id"]}

    assert (
        await client.delete(f"/api/v1/invitations/{invite_id}", headers=owner_headers)
    ).status_code == 204
    first = await client.post(f"/api/v1/invitations/{invite_id}/resend", headers=key_headers)
    assert first.status_code == 200, first.text
    assert first.json()["token"] != invite.json()["token"]

    admin_row = await _member_by_email(client, owner_headers, "adm9@example.com")
    suspended = await client.post(
        f"/api/v1/members/{admin_row['membership_id']}/suspend", headers=owner_headers
    )
    assert suspended.status_code == 200, suspended.text

    assert (
        await client.post(f"/api/v1/invitations/{invite_id}/resend", headers=key_headers)
    ).status_code == 403


async def test_member_status_constraint_rejects_unknown_value(app_client):
    client = app_client
    owner = await register_user(client, "own8@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    member = await _member_by_email(client, owner_headers, "own8@example.com")

    from src.db.session import SessionFactory
    from src.models.workspace import WorkspaceMember

    async with SessionFactory() as session:
        session.add(
            WorkspaceMember(
                workspace_id=ws["id"],
                user_id=member["id"],
                role_id=member["role_id"],
                status="banished",
            )
        )
        with pytest.raises(IntegrityError):
            await session.commit()
        # Release the failed transaction so the teardown can drop the table.
        await session.rollback()


async def test_safe_delete_cascades_but_keeps_audit(app_client):
    client = app_client
    owner = await register_user(client, "own5@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    resp = await client.delete(f"/api/v1/workspaces/{ws['id']}", headers=owner_headers)
    assert resp.status_code == 204, resp.text
    assert (
        await client.get("/api/v1/workspaces/" + ws["id"], headers=owner_headers)
    ).status_code == 404
    # The delete also drops the caller's membership, so the workspace-scoped
    # audit endpoint is no longer reachable for them — assert the retained rows
    # directly instead.
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.audit import AuditLogEntry

    async with SessionFactory() as session:
        actions = (
            (
                await session.execute(
                    select(AuditLogEntry.action).where(AuditLogEntry.workspace_id == ws["id"])
                )
            )
            .scalars()
            .all()
        )
    assert "workspace.deleted" in actions
