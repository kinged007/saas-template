"""MFA requirement: global MFA_REQUIRED setting plus per-workspace flag."""

from src.core.security.totp import current_code, secret_from_base32
from src.settings import settings
from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def _enroll_totp(client, headers):
    setup = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    body = setup.json()
    b32 = body["otpauth_uri"].split("secret=")[1].split("&")[0]
    enable = await client.post(
        "/api/v1/auth/2fa/enable",
        json={"setup_token": body["setup_token"], "code": current_code(secret_from_base32(b32))},
        headers=headers,
    )
    assert enable.status_code == 200, enable.text


async def _patch_mfa(client, ws_id, headers, value):
    return await client.patch(
        f"/api/v1/workspaces/{ws_id}", json={"require_mfa": value}, headers=headers
    )


async def test_mfa_off_by_default(app_client):
    assert settings.mfa_required is False
    client = app_client
    owner = await register_user(client, "mfa-def@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    assert ws["require_mfa"] is False
    me = (await client.get("/api/v1/auth/me", headers=headers)).json()
    entry = next(w for w in me["workspaces"] if w["id"] == ws["id"])
    assert entry["require_mfa"] is False
    # unenrolled access works while nothing requires MFA
    assert (await client.get("/api/v1/members", headers=headers)).status_code == 200


async def test_global_mfa_blocks_workspace_access_until_enrolled(app_client, monkeypatch):
    monkeypatch.setattr(settings, "mfa_required", True)
    client = app_client
    owner = await register_user(client, "mfa-glob@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    session_headers = auth_headers(owner)

    resp = await client.get("/api/v1/members", headers=headers)
    assert resp.status_code == 403
    assert resp.json()["detail"] == "mfa required for this workspace"

    # enrollment itself stays reachable while enforced
    assert (await client.get("/api/v1/auth/me", headers=session_headers)).status_code == 200
    await _enroll_totp(client, session_headers)

    assert (await client.get("/api/v1/members", headers=headers)).status_code == 200


async def test_global_mfa_gates_api_keys_on_owner_enrollment(app_client, monkeypatch):
    client = app_client
    owner = await register_user(client, "mfa-key@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = (
        await client.post(
            "/api/v1/api-keys",
            json={"name": "ci", "permissions": ["member:read"]},
            headers=headers,
        )
    ).json()
    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    monkeypatch.setattr(settings, "mfa_required", True)
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 403

    await _enroll_totp(client, auth_headers(owner))
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200


async def test_workspace_flag_scopes_enforcement_to_that_workspace(app_client):
    client = app_client
    owner = await register_user(client, "mfa-ws@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    other = await create_workspace(client, owner, name="Second")
    other_headers = ws_headers(owner, other["id"])

    resp = await _patch_mfa(client, ws["id"], headers, True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["require_mfa"] is True

    assert (await client.get("/api/v1/members", headers=headers)).status_code == 403
    # the sibling workspace is unaffected
    assert (await client.get("/api/v1/members", headers=other_headers)).status_code == 200

    await _enroll_totp(client, auth_headers(owner))
    assert (await client.get("/api/v1/members", headers=headers)).status_code == 200

    # toggling back off restores access for unenrolled members
    member = await register_user(client, "mfa-plain@example.com")
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "mfa-plain@example.com",
            "role_id": next(r for r in roles if r["name"] == "admin")["id"],
        },
        headers=headers,
    )
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(member),
    )
    member_headers = ws_headers(member, ws["id"])
    assert (await client.get("/api/v1/members", headers=member_headers)).status_code == 403
    assert (await _patch_mfa(client, ws["id"], headers, False)).json()["require_mfa"] is False
    assert (await client.get("/api/v1/members", headers=member_headers)).status_code == 200


async def test_non_member_still_gets_membership_error(app_client, monkeypatch):
    """The MFA gate runs after membership: outsiders learn nothing about flags."""
    monkeypatch.setattr(settings, "mfa_required", True)
    client = app_client
    owner = await register_user(client, "mfa-outer@example.com")
    ws = await create_workspace(client, owner)
    outsider = await register_user(client, "mfa-outsider@example.com")

    resp = await client.get("/api/v1/members", headers=ws_headers(outsider, ws["id"]))
    assert resp.status_code == 403
    assert "not a member" in resp.json()["detail"]


async def test_mfa_flag_rejects_coerced_types(app_client):
    client = app_client
    owner = await register_user(client, "mfa-strict@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await _patch_mfa(client, ws["id"], headers, "yes")
    assert resp.status_code == 422


async def test_global_mfa_blocks_key_permission_routes(app_client, monkeypatch):
    """Session reads via require_key_permission are gated like the rest."""
    monkeypatch.setattr(settings, "mfa_required", True)
    client = app_client
    owner = await register_user(client, "mfa-keyperm@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    for path in ("/api/v1/conversations", "/api/v1/notifications"):
        resp = await client.get(path, headers=headers)
        assert resp.status_code == 403
        assert resp.json()["detail"] == "mfa required for this workspace"

    await _enroll_totp(client, auth_headers(owner))
    for path in ("/api/v1/conversations", "/api/v1/notifications"):
        assert (await client.get(path, headers=headers)).status_code == 200
