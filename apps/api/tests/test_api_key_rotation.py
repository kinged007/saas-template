"""API key rotation: fresh secret rolls, old secret dies, metadata preserved."""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select, update

from src.core.dates import ensure_utc, now_utc
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.settings import settings
from tests.conftest import create_workspace, register_user, ws_headers


async def _create_key(client, headers, name="rotating", permissions=None, body=None):
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "permissions": permissions or ["member:read"], **(body or {})},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_rotate_rolls_secret_and_kills_old_one(app_client):
    client = app_client
    owner = await register_user(client, "ruth@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers)
    old_secret = key["key"]

    resp = await client.post(f"/api/v1/api-keys/{key['id']}/rotate", headers=headers)
    assert resp.status_code == 201, resp.text
    rotated = resp.json()
    assert rotated["id"] == key["id"]
    assert rotated["key"].startswith("sk_live_")
    assert rotated["key"] != old_secret
    assert rotated["key_prefix"] != key["key_prefix"]
    # metadata is untouched — only the secret rolls
    assert rotated["name"] == key["name"]
    assert rotated["permissions"] == key["permissions"]
    assert rotated["usage_quota"] == key["usage_quota"]
    assert rotated["expires_at"] == key["expires_at"]

    # old secret is dead, new secret authenticates
    old_headers = {"Authorization": f"Bearer {old_secret}", "X-Workspace-ID": ws["id"]}
    new_headers = {
        "Authorization": f"Bearer {rotated['key']}",
        "X-Workspace-ID": ws["id"],
    }
    assert (await client.get("/api/v1/members", headers=old_headers)).status_code == 401
    assert (await client.get("/api/v1/members", headers=new_headers)).status_code == 200

    # the list echoes the new prefix and never the secret
    listed = (await client.get("/api/v1/api-keys", headers=headers)).json()
    item = next(k for k in listed if k["id"] == key["id"])
    assert item["key_prefix"] == rotated["key_prefix"]
    assert "key" not in item


async def _wait_for_audit(resource_id: str, action: str, timeout_s: float = 10.0):
    """The audit consumer is a background handler — poll for its row."""
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


async def test_rotate_records_audit_entry(app_client):
    client = app_client
    owner = await register_user(client, "audit-rot@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers)
    old_prefix = key["key_prefix"]
    assert (
        await client.post(f"/api/v1/api-keys/{key['id']}/rotate", headers=headers)
    ).status_code == 201

    entry = await _wait_for_audit(key["id"], "apikey.rotated")
    assert entry.workspace_id == ws["id"]
    assert entry.details["old_key_prefix"] == old_prefix


async def test_rotate_unknown_key_is_404(app_client):
    client = app_client
    owner = await register_user(client, "norotate@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await client.post(
        "/api/v1/api-keys/00000000-0000-0000-0000-000000000000/rotate",
        headers=headers,
    )
    assert resp.status_code == 404


async def test_rotate_another_users_key_is_not_leaked(app_client):
    """Personal scope: another member's key id reads as 404, never 403."""
    client = app_client
    owner = await register_user(client, "owner-rot@example.com")
    ws = await create_workspace(client, owner)
    owner_headers = ws_headers(owner, ws["id"])
    key = await _create_key(client, owner_headers)

    # a second admin in the same workspace still cannot rotate it
    other = await register_user(client, "other-rot@example.com")
    from tests.conftest import auth_headers

    roles = (await client.get("/api/v1/roles", headers=owner_headers)).json()
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "other-rot@example.com",
            "role_id": next(r for r in roles if r["name"] == "admin")["id"],
        },
        headers=owner_headers,
    )
    assert invite.status_code in (200, 201), invite.text
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(other),
    )
    other_headers = ws_headers(other, ws["id"])
    resp = await client.post(f"/api/v1/api-keys/{key['id']}/rotate", headers=other_headers)
    assert resp.status_code == 404


async def test_rotate_revoked_key_conflicts(app_client):
    client = app_client
    owner = await register_user(client, "rev-rot@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers)
    resp = await client.delete(f"/api/v1/api-keys/{key['id']}", headers=headers)
    assert resp.status_code == 204
    resp = await client.post(f"/api/v1/api-keys/{key['id']}/rotate", headers=headers)
    assert resp.status_code == 409


async def test_rotate_expired_key_conflicts(app_client):
    client = app_client
    owner = await register_user(client, "exp-rot@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(
        client, headers, body={"expires_at": (now_utc() + timedelta(days=1)).isoformat()}
    )
    async with SessionFactory() as session:
        await session.execute(
            update(ApiKey)
            .where(ApiKey.id == key["id"])
            .values(expires_at=now_utc() - timedelta(seconds=1))
        )
        await session.commit()
    resp = await client.post(f"/api/v1/api-keys/{key['id']}/rotate", headers=headers)
    assert resp.status_code == 409


async def test_default_expire_days_applies_when_no_expiry_given(app_client, monkeypatch):
    monkeypatch.setattr(settings, "api_key_default_expire_days", 30)
    client = app_client
    owner = await register_user(client, "def-exp@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers)
    assert key["expires_at"] is not None
    expires = ensure_utc(datetime.fromisoformat(key["expires_at"]))
    delta = expires - now_utc()
    assert timedelta(days=29) < delta <= timedelta(days=30, seconds=60)


async def test_explicit_expiry_wins_over_default(app_client, monkeypatch):
    monkeypatch.setattr(settings, "api_key_default_expire_days", 30)
    client = app_client
    owner = await register_user(client, "exp-win@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    wanted = now_utc() + timedelta(days=7)
    key = await _create_key(client, headers, body={"expires_at": wanted.isoformat()})
    assert key["expires_at"] is not None
    got = ensure_utc(datetime.fromisoformat(key["expires_at"]))
    assert abs((got - wanted).total_seconds()) < 5


async def test_no_default_expiry_by_default(app_client):
    assert settings.api_key_default_expire_days == 0
    client = app_client
    owner = await register_user(client, "no-def-exp@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers)
    assert key["expires_at"] is None
