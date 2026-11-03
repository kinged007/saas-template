"""PATCH /api-keys/{id}: partial key edit (name, quota, expiry)."""

import asyncio
from datetime import datetime, timedelta

from sqlalchemy import select

from src.core.dates import ensure_utc, now_utc
from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry
from tests.conftest import create_workspace, register_user, ws_headers


async def _create_key(client, headers, name="editable", body=None):
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "permissions": ["member:read"], **(body or {})},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


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


async def _setup(app_client, email="key-edit@example.com"):
    client = app_client
    owner = await register_user(client, email)
    ws = await create_workspace(client, owner)
    return client, ws_headers(owner, ws["id"]), ws


async def test_rename_updates_name_only(app_client):
    client, headers, ws = await _setup(app_client)
    key = await _create_key(client, headers)

    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}", json={"name": "renamed"}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "renamed"
    assert body["expires_at"] == key["expires_at"]
    assert body["usage_quota"] == key["usage_quota"]
    assert "key" not in body  # the secret is never re-issued by an edit

    entry = await _wait_for_audit(key["id"], "apikey.updated")
    assert entry.details["name"] == {"from": "editable", "to": "renamed"}


async def test_quota_set_and_cleared(app_client):
    client, headers, ws = await _setup(app_client)
    key = await _create_key(client, headers)
    assert key["usage_quota"] is None

    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}", json={"usage_quota": 50}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["usage_quota"] == 50

    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}", json={"usage_quota": None}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["usage_quota"] is None


async def test_expiry_set_and_cleared(app_client):
    client, headers, ws = await _setup(app_client)
    key = await _create_key(client, headers)

    wanted = now_utc() + timedelta(days=30)
    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}",
        json={"expires_at": wanted.isoformat()},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    got = ensure_utc(datetime.fromisoformat(resp.json()["expires_at"]))
    assert abs((got - wanted).total_seconds()) < 5 * 60

    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}", json={"expires_at": None}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["expires_at"] is None


async def test_past_and_naive_expiry_rejected(app_client):
    client, headers, ws = await _setup(app_client)
    key = await _create_key(client, headers)

    past = await client.patch(
        f"/api/v1/api-keys/{key['id']}",
        json={"expires_at": (now_utc() - timedelta(days=1)).isoformat()},
        headers=headers,
    )
    assert past.status_code == 422, past.text

    naive = await client.patch(
        f"/api/v1/api-keys/{key['id']}",
        json={"expires_at": "2027-01-01T00:00:00"},
        headers=headers,
    )
    assert naive.status_code == 422, naive.text


async def test_empty_patch_and_blank_name_rejected(app_client):
    client, headers, ws = await _setup(app_client)
    key = await _create_key(client, headers)

    resp = await client.patch(f"/api/v1/api-keys/{key['id']}", json={}, headers=headers)
    assert resp.status_code == 422, resp.text

    resp = await client.patch(f"/api/v1/api-keys/{key['id']}", json={"name": "  "}, headers=headers)
    assert resp.status_code == 422, resp.text


async def test_edit_another_users_key_is_not_leaked(app_client):
    from tests.conftest import auth_headers

    client, headers, ws = await _setup(app_client, email="key-owner@example.com")
    key = await _create_key(client, headers)

    # A fellow admin in the same workspace still must not edit it.
    other = await register_user(client, "key-stranger@example.com")
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "key-stranger@example.com",
            "role_id": next(r for r in roles if r["name"] == "admin")["id"],
        },
        headers=headers,
    )
    assert invite.status_code in (200, 201), invite.text
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(other),
    )
    other_headers = ws_headers(other, ws["id"])
    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}", json={"name": "hijacked"}, headers=other_headers
    )
    # Personal scope: 404, not 403, so the key id's existence is not leaked.
    assert resp.status_code == 404, resp.text
    assert "hijacked" not in (await client.get("/api/v1/api-keys", headers=headers)).text


async def test_unknown_key_is_404(app_client):
    client, headers, ws = await _setup(app_client)
    resp = await client.patch(
        "/api/v1/api-keys/00000000-0000-0000-0000-000000000000",
        json={"name": "ghost"},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_noop_edit_returns_key(app_client):
    client, headers, ws = await _setup(app_client)
    key = await _create_key(client, headers)

    resp = await client.patch(
        f"/api/v1/api-keys/{key['id']}", json={"name": key["name"]}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == key["name"]
