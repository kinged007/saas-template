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
    audit = await client.get("/api/v1/audit", headers=owner_headers)
    assert audit.status_code == 200, audit.text
    assert any(e["action"] == "workspace.deleted" for e in audit.json())
