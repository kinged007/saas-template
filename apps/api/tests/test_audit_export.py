"""GET /audit/export: filtered audit dump in JSON and CSV."""

import asyncio
import csv
import io

from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry
from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


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


async def _setup(app_client):
    """One workspace with audit history: a created API key leaves apikey.created."""
    client = app_client
    owner = await register_user(client, "audit-exp@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    key = (
        await client.post(
            "/api/v1/api-keys",
            json={"name": "export-probe", "permissions": ["member:read"]},
            headers=headers,
        )
    ).json()
    await _wait_for_audit(key["id"], "apikey.created")
    return client, headers, ws, key


async def test_export_json_returns_entries(app_client):
    client, headers, ws, key = await _setup(app_client)

    resp = await client.get("/api/v1/audit/export?format=json", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert "attachment" in resp.headers["content-disposition"]
    assert resp.headers["X-Truncated"] == "false"
    body = resp.json()
    assert body["truncated"] is False
    assert body["exported_at"]
    actions = [e["action"] for e in body["audit"]]
    assert "apikey.created" in actions
    entry = next(e for e in body["audit"] if e["action"] == "apikey.created")
    assert entry["actor_email"] == "audit-exp@example.com"
    assert entry["resource_id"] == key["id"]
    assert "source_event_id" not in entry


async def test_export_csv_matches_bundle_columns(app_client):
    client, headers, ws, key = await _setup(app_client)

    resp = await client.get("/api/v1/audit/export?format=csv", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert len(rows) >= 1
    assert set(rows[0]) == {
        "id",
        "created_at",
        "actor_email",
        "action",
        "resource_type",
        "resource_id",
        "ip_address",
    }
    assert any(r["action"] == "apikey.created" for r in rows)


async def test_export_filters_narrow_results(app_client):
    client, headers, ws, key = await _setup(app_client)

    full = (await client.get("/api/v1/audit/export?format=json", headers=headers)).json()
    assert len(full["audit"]) >= 1

    filtered = (
        await client.get("/api/v1/audit/export?format=json&action=apikey.created", headers=headers)
    ).json()
    assert len(filtered["audit"]) >= 1
    assert all(e["action"] == "apikey.created" for e in filtered["audit"])

    empty = (
        await client.get("/api/v1/audit/export?format=json&action=does.not.exist", headers=headers)
    ).json()
    assert empty["audit"] == []
    assert empty["truncated"] is False

    searched = (
        await client.get(
            "/api/v1/audit/export?format=json&q=audit-exp@example.com", headers=headers
        )
    ).json()
    assert any(e["actor_email"] == "audit-exp@example.com" for e in searched["audit"])

    by_resource = (
        await client.get("/api/v1/audit/export?format=json&resource_type=apikey", headers=headers)
    ).json()
    assert all(e["resource_type"] == "apikey" for e in by_resource["audit"])


async def test_export_rejects_unknown_format(app_client):
    client, headers, ws, key = await _setup(app_client)
    resp = await client.get("/api/v1/audit/export?format=xml", headers=headers)
    assert resp.status_code == 422


async def test_export_requires_audit_read(app_client):
    client, headers, ws, key = await _setup(app_client)

    viewer = await register_user(client, "audit-viewer@example.com")
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    invite = await client.post(
        "/api/v1/invitations",
        json={
            "email": "audit-viewer@example.com",
            "role_id": next(r for r in roles if r["name"] == "viewer")["id"],
        },
        headers=headers,
    )
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(viewer),
    )
    viewer_headers = ws_headers(viewer, ws["id"])
    resp = await client.get("/api/v1/audit/export?format=json", headers=viewer_headers)
    assert resp.status_code == 403


async def test_export_writes_audit_entry(app_client):
    client, headers, ws, key = await _setup(app_client)

    assert (await client.get("/api/v1/audit/export?format=csv", headers=headers)).status_code == 200
    entry = await _wait_for_audit(ws["id"], "audit.exported")
    assert entry.details["format"] == "csv"
    assert entry.details["count"] >= 1
    assert entry.details["truncated"] is False
