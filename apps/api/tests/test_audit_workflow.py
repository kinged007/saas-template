"""API-level tests: the audit workflow persists every audit event to the DB.

The app wires the full workflow registry into the in-process bus, so a
published `audit.entry.created` event must end up as an AuditLogEntry row
(after the background consumer task runs).
"""

from __future__ import annotations

import asyncio
import inspect

from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry


async def _audit_rows():
    async with SessionFactory() as session:
        result = await session.execute(select(AuditLogEntry).order_by(AuditLogEntry.created_at))
        return list(result.scalars().all())


async def _wait_for(predicate, timeout_secs: float = 3.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_secs
    while loop.time() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(interval)
    return False


async def _audit_actions() -> list[str]:
    return [row.action for row in await _audit_rows()]


async def _actions_equal(expected: list[str]) -> bool:
    return await _audit_actions() == expected


async def _actions_contain(action: str) -> bool:
    return action in await _audit_actions()


async def test_register_persists_audit_row(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "audit@example.com", "password": "Password123!", "display_name": "Audit"},
    )
    assert await _wait_for(lambda: _actions_equal(["user.register"]))
    rows = await _audit_rows()
    assert len(rows) == 1
    row = rows[0]
    assert row.workspace_id is None  # user-scoped action
    assert row.resource_type == "user"
    assert row.action == "user.register"
    assert row.details["email"] == "audit@example.com"


async def test_login_refresh_logout_persist_audit_rows(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "audit2@example.com", "password": "Password123!", "display_name": "Audit"},
    )
    assert await _wait_for(lambda: _actions_contain("user.register"))

    resp = await app_client.post(
        "/api/v1/auth/login", json={"email": "audit2@example.com", "password": "Password123!"}
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert await _wait_for(lambda: _actions_contain("user.login"))

    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200
    assert await _wait_for(lambda: _actions_contain("user.token_refresh"))

    resp = await app_client.post(
        "/api/v1/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 204
    assert await _wait_for(lambda: _actions_contain("user.logout"))

    actions = await _audit_actions()
    assert actions == ["user.register", "user.login", "user.token_refresh", "user.logout"]
    for row in await _audit_rows():
        assert row.workspace_id is None
        assert row.resource_type == "user"


async def test_workspace_create_persists_workspace_audit(app_client):
    from tests.conftest import create_workspace, register_user

    tokens = await register_user(app_client, "audit3@example.com")
    workspace = await create_workspace(app_client, tokens, name="Audit Corp")
    assert await _wait_for(lambda: _actions_contain("workspace.created"))

    rows = [r for r in await _audit_rows() if r.action == "workspace.created"]
    assert len(rows) == 1
    row = rows[0]
    assert row.workspace_id == workspace["id"]
    assert row.resource_type == "workspace"
    assert row.resource_id == workspace["id"]
    assert row.actor_user_id is not None


async def test_api_key_create_persists_audit(app_client):
    from tests.conftest import create_workspace, register_user, ws_headers

    tokens = await register_user(app_client, "audit4@example.com")
    workspace = await create_workspace(app_client, tokens)
    assert await _wait_for(lambda: _actions_contain("workspace.created"))

    resp = await app_client.post(
        "/api/v1/api-keys",
        json={"name": "ci", "permissions": ["workspace:read"]},
        headers=ws_headers(tokens, workspace["id"]),
    )
    assert resp.status_code == 201, resp.text
    assert await _wait_for(lambda: _actions_contain("apikey.created"))
    rows = [r for r in await _audit_rows() if r.action == "apikey.created"]
    assert len(rows) == 1
    assert rows[0].workspace_id == workspace["id"]
    assert rows[0].resource_type == "apikey"
    assert rows[0].details["name"] == "ci"

    key_id = resp.json()["id"]
    resp = await app_client.delete(
        f"/api/v1/api-keys/{key_id}",
        headers=ws_headers(tokens, workspace["id"]),
    )
    assert resp.status_code == 204, resp.text
    assert await _wait_for(lambda: _actions_contain("apikey.revoked"))


async def test_audit_rows_carry_ip_address(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={"email": "audit5@example.com", "password": "Password123!", "display_name": "Audit"},
    )
    assert await _wait_for(lambda: _actions_equal(["user.register"]))
    rows = await _audit_rows()
    assert rows[0].ip_address is not None  # client IP recorded
    assert rows[0].ip_address != ""
