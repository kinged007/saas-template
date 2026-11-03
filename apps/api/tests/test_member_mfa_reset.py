"""POST /members/{id}/reset-mfa: manager-only TOTP recovery."""

import asyncio

from sqlalchemy import select

from src.core.security.totp import current_code, secret_from_base32
from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry
from src.models.two_factor import UserTotpCredential
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)


async def _add_member(client, owner_tokens, ws, email: str, role_name: str):
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))
    role = next(r for r in roles.json() if r["name"] == role_name)
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role["id"]},
        headers=ws_headers(owner_tokens, ws["id"]),
    )
    invite = resp.json()
    user = await register_user(client, email)
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(user),
    )
    members = await client.get("/api/v1/members", headers=ws_headers(owner_tokens, ws["id"]))
    return user, next(m for m in members.json() if m["email"] == email)


async def _enroll(client, headers):
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


async def _wait_for_audit(resource_id: str, action: str, timeout_s: float = 10.0):
    for _ in range(int(timeout_s * 10)):
        async with SessionFactory() as session:
            entry = (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.resource_id == resource_id,
                        AuditLogEntry.action == action,
                    )
                )
            ).scalar_one_or_none()
            if entry is not None:
                return entry
        await asyncio.sleep(0.1)
    raise AssertionError(f"no {action} audit entry for {resource_id}")


async def test_admin_resets_member_mfa(app_client):
    client = app_client
    owner = await register_user(client, "mfa-adm@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    member, row = await _add_member(client, owner, ws, "locked@example.com", "editor")
    await _enroll(client, auth_headers(member))

    # enrolled: password login now challenges instead of issuing tokens
    challenged = await client.post(
        "/api/v1/auth/login", json={"email": "locked@example.com", "password": "Password123!"}
    )
    assert challenged.status_code == 401

    resp = await client.post(
        f"/api/v1/members/{row['membership_id']}/reset-mfa", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "id": row["membership_id"],
        "user_id": row["id"],
        "totp_enabled": False,
    }

    async with SessionFactory() as session:
        assert await session.get(UserTotpCredential, row["id"]) is None

    # login works without a challenge again, and the member can re-enroll
    assert (
        await client.post(
            "/api/v1/auth/login",
            json={"email": "locked@example.com", "password": "Password123!"},
        )
    ).status_code == 200
    await _enroll(client, auth_headers(member))

    entry = await _wait_for_audit(row["membership_id"], "mfa.reset")
    assert entry.workspace_id == ws["id"]
    assert entry.details["target_user_id"] == row["id"]


async def test_reset_is_idempotent_without_enrollment(app_client):
    client = app_client
    owner = await register_user(client, "mfa-idem@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    _, row = await _add_member(client, owner, ws, "plain2@example.com", "viewer")
    resp = await client.post(
        f"/api/v1/members/{row['membership_id']}/reset-mfa", headers=owner_headers
    )
    assert resp.status_code == 200, resp.text


async def test_self_reset_is_refused(app_client):
    client = app_client
    owner = await register_user(client, "mfa-self@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    members = (await client.get("/api/v1/members", headers=owner_headers)).json()
    own = next(m for m in members if m["email"] == "mfa-self@example.com")

    resp = await client.post(
        f"/api/v1/members/{own['membership_id']}/reset-mfa", headers=owner_headers
    )
    assert resp.status_code == 409


async def test_viewer_cannot_reset_mfa(app_client):
    client = app_client
    owner = await register_user(client, "mfa-perm@example.com")
    ws = await create_workspace(client, owner)

    viewer, _ = await _add_member(client, owner, ws, "looker@example.com", "viewer")
    _, row = await _add_member(client, owner, ws, "target@example.com", "viewer")
    resp = await client.post(
        f"/api/v1/members/{row['membership_id']}/reset-mfa",
        headers=ws_headers(viewer, ws["id"]),
    )
    assert resp.status_code == 403


async def test_reset_unknown_membership_is_404(app_client):
    client = app_client
    owner = await register_user(client, "mfa-404@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])

    resp = await client.post(
        "/api/v1/members/00000000-0000-0000-0000-000000000000/reset-mfa",
        headers=owner_headers,
    )
    assert resp.status_code == 404
