"""API-level tests: the audit workflow persists every audit event to the DB.

The app wires the full workflow registry into the in-process bus, so a
published `audit.entry.created` event must end up as an AuditLogEntry row
(after the background consumer task runs).
"""

from __future__ import annotations

import asyncio
import inspect
import ipaddress
import re
from pathlib import Path

import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry

COMPOSE = Path(__file__).resolve().parents[3] / "infra/docker/docker-compose.prod.yml"


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
        json={
            "email": "audit@example.com",
            "password": "Password123!",
            "first_name": "Audit",
            "last_name": "User",
        },
    )
    assert await _wait_for(
        lambda: _actions_equal(["user.register", "user.email_verification_sent"])
    )
    rows = await _audit_rows()
    assert len(rows) == 2
    row = next(r for r in rows if r.action == "user.register")
    assert row.workspace_id is None  # user-scoped action
    assert row.resource_type == "user"
    assert row.details["email"] == "audit@example.com"


async def test_login_refresh_logout_persist_audit_rows(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "audit2@example.com",
            "password": "Password123!",
            "first_name": "Audit",
            "last_name": "User",
        },
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
    assert actions == [
        "user.register",
        "user.email_verification_sent",
        "user.login",
        "user.token_refresh",
        "user.logout",
    ]
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


async def test_session_revoke_persists_audit_rows(app_client):
    from tests.conftest import auth_headers, login, register_user

    client = app_client
    await register_user(client, "audit6@example.com")
    t2 = await login(client, "audit6@example.com")
    h2 = auth_headers(t2)
    assert await _wait_for(lambda: _actions_contain("user.login"))

    resp = await client.get("/api/v1/auth/sessions", headers=h2)
    assert resp.status_code == 200, resp.text
    other = next(s for s in resp.json() if not s["current"])
    resp = await client.delete(f"/api/v1/auth/sessions/{other['id']}", headers=h2)
    assert resp.status_code == 204, resp.text
    assert await _wait_for(lambda: _actions_contain("user.session_revoked"))

    t3 = await login(client, "audit6@example.com")
    resp = await client.delete("/api/v1/auth/sessions", headers=auth_headers(t3))
    assert resp.status_code == 204, resp.text
    assert await _wait_for(lambda: _actions_contain("user.sessions_revoked"))

    rows = [r for r in await _audit_rows() if r.action.startswith("user.session")]
    assert [r.action for r in rows] == ["user.session_revoked", "user.sessions_revoked"]
    for row in rows:
        assert row.workspace_id is None
        assert row.resource_type == "user"


async def test_audit_rows_carry_ip_address(app_client):
    await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "audit5@example.com",
            "password": "Password123!",
            "first_name": "Audit",
            "last_name": "User",
        },
    )
    assert await _wait_for(
        lambda: _actions_equal(["user.register", "user.email_verification_sent"])
    )
    rows = await _audit_rows()
    assert rows[0].ip_address == "127.0.0.1"  # the ASGI peer, exactly


async def test_audit_row_ignores_forwarded_for_without_proxy_middleware(app_client):
    """App code must not read X-Forwarded-For itself — only uvicorn's middleware does.

    With no ProxyHeadersMiddleware in the chain, a client-supplied header changes nothing.
    """
    await app_client.post(
        "/api/v1/auth/register",
        json={
            "email": "audit5@example.com",
            "password": "Password123!",
            "first_name": "Audit",
            "last_name": "User",
        },
        headers={"X-Forwarded-For": "203.0.113.9"},
    )
    assert await _wait_for(
        lambda: _actions_equal(["user.register", "user.email_verification_sent"])
    )
    rows = await _audit_rows()
    assert rows[0].ip_address == "127.0.0.1"


async def test_audit_row_records_forwarded_client_from_trusted_proxy(app):
    """Behind the shipped nginx, uvicorn --proxy-headers rewrites scope["client"]
    from X-Forwarded-For, so the end user's address is what lands in the audit log."""
    middleware = ProxyHeadersMiddleware(app, trusted_hosts="10.0.0.5")
    transport = ASGITransport(app=middleware, client=("10.0.0.5", 40000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "audit7@example.com",
                "password": "Password123!",
                "first_name": "Audit",
                "last_name": "User",
            },
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
    assert resp.status_code == 201, resp.text
    assert await _wait_for(
        lambda: _actions_equal(["user.register", "user.email_verification_sent"])
    )
    rows = await _audit_rows()
    assert rows[0].ip_address == "203.0.113.9"


async def test_forwarded_for_from_untrusted_peer_is_ignored(app):
    """Why --forwarded-allow-ips must name the proxy instead of '*'.

    Under a narrowed list uvicorn walks X-Forwarded-For from the right and keeps
    the address of the connecting peer. Under '*' it takes the leftmost entry
    verbatim, so any peer can declare its own recorded IP.
    """
    middleware = ProxyHeadersMiddleware(app, trusted_hosts="10.0.0.5")
    transport = ASGITransport(app=middleware, client=("198.51.100.7", 40000))
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        resp = await client.post(
            "/api/v1/auth/register",
            json={
                "email": "audit8@example.com",
                "password": "Password123!",
                "first_name": "Audit",
                "last_name": "User",
            },
            headers={"X-Forwarded-For": "203.0.113.9"},
        )
    assert resp.status_code == 201, resp.text
    assert await _wait_for(
        lambda: _actions_equal(["user.register", "user.email_verification_sent"])
    )
    rows = await _audit_rows()
    assert rows[0].ip_address == "198.51.100.7"


def test_prod_compose_trusts_only_the_pinned_proxy_network():
    """The shipped value the tests above stand in for must stay narrow.

    Reverting docker-compose.prod.yml to '--forwarded-allow-ips=*' leaves every
    other test green while reopening the spoofing hole, so pin the config too:
    every entry must be a network, no entry may be a default route, the subnet
    the compose file pins nginx to must be inside the trusted set, and
    --proxy-headers must be on or the allowlist never applies.
    """
    compose = yaml.safe_load(COMPOSE.read_text())
    command = compose["services"]["api"]["command"]
    default = re.search(r"--forwarded-allow-ips=\$\{FORWARDED_ALLOW_IPS:-([^}]+)\}", command)
    assert default, f"no --forwarded-allow-ips default in: {command}"
    trusted = [
        ipaddress.ip_network(entry.strip(), strict=False) for entry in default.group(1).split(",")
    ]
    assert all(net.prefixlen > 0 for net in trusted), (
        f"FORWARDED_ALLOW_IPS default trusts every peer: {trusted}"
    )
    subnet = ipaddress.ip_network(compose["networks"]["default"]["ipam"]["config"][0]["subnet"])
    assert all(subnet.subnet_of(net) for net in trusted), (
        f"pinned subnet {subnet} outside FORWARDED_ALLOW_IPS default {trusted}"
    )
    assert "--proxy-headers" in command, f"--proxy-headers missing from: {command}"
