"""API-level tests: the audit workflow persists every audit event to the DB.

The app wires the full workflow registry into the in-process bus, so a
published `audit.entry.created` event must end up as an AuditLogEntry row
(after the background consumer task runs).

The tail of the file covers the write path's idempotency: JetStream is
at-least-once, so one redelivered event must leave exactly one audit row
while two genuine failures still leave two.
"""

from __future__ import annotations

import ast
import asyncio
import inspect
import ipaddress
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware, _TrustedHosts

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry

COMPOSE = Path(__file__).resolve().parents[3] / "infra/docker/docker-compose.prod.yml"
DOCKERFILE_API = Path(__file__).resolve().parents[3] / "infra/docker/Dockerfile.api"
NGINX_CONF = Path(__file__).resolve().parents[3] / "infra/docker/nginx.conf"
WORKFLOWS = Path(__file__).resolve().parents[1] / "src/workflows/__init__.py"


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

    # the token the client holds after the rotation — the pre-refresh one is
    # already rotated, and revoking a rotated row is a no-op by design
    resp = await app_client.post(
        "/api/v1/auth/logout", json={"refresh_token": resp.json()["refresh_token"]}
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


async def test_refresh_token_reuse_audit_blames_nobody(app_client):
    """The reuse action must not name the user as the actor who did it.

    The replay proves a token escaped, not who sent it, and two tabs of one
    browser can trigger it by racing. This row is what a responder reads to
    decide whether the account owner needs to be told.
    """
    from tests.conftest import login, register_user

    client = app_client
    await register_user(client, "audit-reuse@example.com")
    t2 = await login(client, "audit-reuse@example.com")
    assert await _wait_for(lambda: _actions_contain("user.login"))

    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    ).status_code == 200
    assert (
        await client.post("/api/v1/auth/refresh", json={"refresh_token": t2["refresh_token"]})
    ).status_code == 401
    assert await _wait_for(lambda: _actions_contain("user.refresh_token_reuse"))

    [row] = [r for r in await _audit_rows() if r.action == "user.refresh_token_reuse"]
    assert row.actor_user_id is None
    assert row.resource_type == "user"
    assert row.details["revoked_count"] >= 1
    assert row.details["session_id"]


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
    uvicorn must parse every entry as an IP or network (strict=True — anything
    else is demoted to an untrusted literal that silently matches no peer), no
    entry may be a default route, the subnet the compose file pins nginx to
    must be inside the trusted set, and --proxy-headers must be on or the
    allowlist never applies. The value is parsed through uvicorn's own
    _TrustedHosts so the guard cannot drift from what uvicorn actually does
    with it (uv.lock pins the version).
    """
    compose = yaml.safe_load(COMPOSE.read_text())
    command = compose["services"]["api"]["command"]
    default = re.search(r"--forwarded-allow-ips=\$\{FORWARDED_ALLOW_IPS:-([^}]+)\}", command)
    assert default, f"no --forwarded-allow-ips default in: {command}"
    trusted = _TrustedHosts(default.group(1))
    assert trusted.always_trust is False and not trusted.trusted_literals, (
        f"FORWARDED_ALLOW_IPS default trusts every peer or carries an entry "
        f"uvicorn cannot parse (silently untrusted): {default.group(1)}"
    )
    nets = list(trusted.trusted_networks) + [
        ipaddress.ip_network(ip) for ip in trusted.trusted_hosts
    ]
    assert all(net.prefixlen > 0 for net in trusted.trusted_networks), (
        f"FORWARDED_ALLOW_IPS default trusts every peer: {default.group(1)}"
    )
    subnet = ipaddress.ip_network(compose["networks"]["default"]["ipam"]["config"][0]["subnet"])
    assert all(subnet.subnet_of(net) for net in nets), (
        f"pinned subnet {subnet} outside FORWARDED_ALLOW_IPS default {default.group(1)}"
    )
    assert "--proxy-headers" in command, f"--proxy-headers missing from: {command}"


def test_image_cmd_carries_proxy_flags():
    """A direct docker run, Kubernetes manifest or buildpack launch uses the
    image CMD — compose's `command:` overrides it, so the flags must be on the
    default or every non-compose deployment records the proxy's address and the
    IP-keyed limiters collapse. The allowlist is wired to FORWARDED_ALLOW_IPS
    with a loopback-only default: outside compose nothing remote is trusted
    until the operator names the proxy.
    """
    cmd = re.search(r"^CMD (.+)$", DOCKERFILE_API.read_text(), re.MULTILINE)
    assert cmd, "no CMD line in Dockerfile.api"
    line = cmd.group(1)
    default = re.search(r'--forwarded-allow-ips=\\"\$\{FORWARDED_ALLOW_IPS:-([^}]+)\}\\"', line)
    assert default, (
        f"image CMD must wire --forwarded-allow-ips to FORWARDED_ALLOW_IPS, "
        f"quoted so a value containing spaces stays one argv: {line}"
    )
    trusted = _TrustedHosts(default.group(1))
    assert trusted.always_trust is False and not trusted.trusted_literals, (
        f"image CMD default trusts every peer or carries an entry uvicorn "
        f"cannot parse (silently untrusted): {default.group(1)}"
    )
    assert "--proxy-headers" in line, f"--proxy-headers missing from: {line}"


def test_nginx_ws_location_forwards_client_ip():
    """Without X-Forwarded-For on the /api/v1/ws location, uvicorn's client is
    the connecting peer alone — nginx's address, not the end user's.
    X-Forwarded-Proto keeps the scheme honest (ws vs wss) exactly as the /api/
    location already does. No ws route reads scope["client"] today, so the
    headers keep future client-IP-dependent ws code correct rather than fix a
    live misattribution.
    """
    ws = re.search(r"location /api/v1/ws \{([^}]*)\}", NGINX_CONF.read_text())
    assert ws, "no /api/v1/ws location in nginx.conf"
    for header in ("X-Forwarded-For", "X-Forwarded-Proto"):
        assert f"proxy_set_header {header}" in ws.group(1), (
            f"{header} missing from /api/v1/ws location: {ws.group(0)}"
        )


def _nginx_block_body(kind: str, anchor: str) -> str:
    """Inner text of the first top-level `<kind> <anchor> { … }`.

    Non-greedy so it stops at the block's own closing brace; the geo/map
    blocks carry no nested braces. `anchor` is regex-safe.
    """
    body = NGINX_CONF.read_text()
    match = re.search(rf"{kind}\s+{anchor}\s*\{{(.*?)\}}", body, re.DOTALL)
    assert match, f"no {kind} {anchor} {{...}} block in nginx.conf"
    return match.group(1)


def _forwarded_proto(trusted: str, forwarded: str, local_scheme: str = "http") -> str:
    """Evaluate the shipped `map ... $forwarded_proto` block the way nginx does.

    nginx listens on plain :80, so `$scheme` is always `http` here — that is
    `local_scheme`, the fallback when no rule matches. Regex keys (`~*`
    case-insensitive) match first-in-order; a bare key is exact; `default` is
    the fallback. Mirrors nginx's documented map semantics for the constructs
    the conf uses, so the guard asserts shipped behaviour, not a retyping.
    """
    block = _nginx_block_body(
        "map", r'"\$trusted_proxy:\$http_x_forwarded_proto"\s+\$forwarded_proto'
    )
    key = f"{trusted}:{forwarded}"
    default = None
    for line in block.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("default"):
            default = line.split(None, 1)[1].rstrip(";").strip().strip('"')
            continue
        token, _, value = line.partition(" ")
        token = token.strip().strip('"')
        value = value.strip().rstrip(";").strip().strip('"')
        if token.startswith("~*"):
            matched = re.search(token[2:], key, re.IGNORECASE) is not None
        elif token.startswith("~"):
            matched = re.search(token[1:], key) is not None
        else:
            matched = token == key
        if matched:
            return local_scheme if value == "$scheme" else value
    assert default is not None, "map block has no default"
    return local_scheme if default == "$scheme" else default


@pytest.mark.parametrize(
    "trusted,forwarded,expected",
    [
        ("1", "https", "https"),
        ("1", "HTTPS", "https"),
        ("1", "https, http", "https"),
        ("1", "http", "http"),
        ("1", "HTTP", "http"),
        ("1", "http, https", "http"),
        ("1", "", "http"),
        ("1", "gopher", "http"),
        ("1", "httpsfoo", "http"),
        ("1", "https-x", "http"),
        ("0", "https", "http"),
        ("0", "HTTPS", "http"),
        ("0", "https, http", "http"),
    ],
)
def test_nginx_forwarded_proto_matches_trusted_proxy_header(trusted, forwarded, expected):
    """A trusted TLS-terminating load balancer's scheme reaches the API; a
    spoofed header from anyone else is dropped to the local $scheme.

    The API only sets Secure on the refresh cookie when it sees https (see
    `cookie_secure_for`), so an https client behind the external terminator
    must land here as https while an untrusted client cannot.
    """
    assert _forwarded_proto(trusted, forwarded) == expected


def test_nginx_geo_and_map_blocks_are_at_http_level():
    """The geo and map blocks sit at http level, before any server{}.

    Both directives are rejected inside `server{}` — `nginx -t` fails with
    "directive is not allowed here" and the container refuses to start — but
    the guards above read the conf as plain text and would still pass, so an
    indented or misplaced edit goes unnoticed.
    """
    lines = NGINX_CONF.read_text().splitlines()
    server_line = next(i for i, ln in enumerate(lines) if ln.startswith("server {"))
    directives = ("geo $trusted_proxy", 'map "$trusted_proxy:$http_x_forwarded_proto"')
    for directive in directives:
        at_column_zero = [i for i, ln in enumerate(lines) if ln.startswith(directive)]
        assert at_column_zero, f"{directive!r} is indented (nested in server{{}}?)"
        assert min(at_column_zero) < server_line, (
            f"{directive} is declared inside server{{}}: nginx -t would fail"
        )


def test_nginx_locations_forward_the_trusted_proto_variable():
    """Both proxied locations send X-Forwarded-Proto from the mapped
    variable, never the always-http $scheme."""
    for loc in (r"/api/", r"/api/v1/ws"):
        match = re.search(rf"location {re.escape(loc)} \{{([^}}]*)\}}", NGINX_CONF.read_text())
        assert match, f"no {loc} location in nginx.conf"
        body = match.group(1)
        assert "proxy_set_header X-Forwarded-Proto $scheme" not in body, (
            f"{loc} forwards $scheme (always http here) instead of the mapped variable"
        )
        assert "proxy_set_header X-Forwarded-Proto $forwarded_proto" in body, (
            f"{loc} must forward X-Forwarded-Proto from $forwarded_proto"
        )


def test_nginx_trusted_proxy_set_is_not_everyone():
    """The geo set defaults to untrusted, trusts no default route, and still
    covers the subnet compose pins nginx to."""
    block = _nginx_block_body("geo", r"\$trusted_proxy")
    assert re.search(r"default\s+0\b", block), f"geo must default to untrusted (0):\n{block}"
    assert "0.0.0.0/0" not in block and "::/0" not in block, (
        f"geo trusts every peer via a default route:\n{block}"
    )
    pinned = re.search(r"subnet:\s*(\S+)", COMPOSE.read_text())
    assert pinned, "no pinned subnet in docker-compose.prod.yml"
    pinned_net = ipaddress.ip_network(pinned.group(1).strip().strip('"'))
    cidrs = re.findall(r"(\d+\.\d+\.\d+\.\d+/\d+)", block)
    assert cidrs, f"no CIDR ranges in geo block:\n{block}"
    assert any(pinned_net.subnet_of(ipaddress.ip_network(cidr)) for cidr in cidrs), (
        f"pinned subnet {pinned_net} is not inside any trusted range: {cidrs}"
    )


async def _email_failed_rows(resource_id: str) -> list[AuditLogEntry]:
    async with SessionFactory() as session:
        result = await session.execute(
            select(AuditLogEntry).where(
                AuditLogEntry.action == "invitation.email_failed",
                AuditLogEntry.resource_id == resource_id,
            )
        )
        return list(result.scalars().all())


async def _publish_failed_invitation(bus, invitation_id: str | None = None) -> str:
    """Drive the invitation workflow with a send that fails."""
    from src.events.subjects import Subjects

    invitation_id = invitation_id or str(uuid.uuid4())
    await bus.publish(
        Subjects.WORKSPACE_INVITATION_CREATED,
        {
            "workspace_id": str(uuid.uuid4()),
            "workspace_name": "Acme Corp",
            "email": "unreachable@example.com",
            "invitation_id": invitation_id,
            "invited_by_user_id": str(uuid.uuid4()),
            "invited_by_name": "Owner",
            "is_registered": False,
        },
    )
    return invitation_id


class _NoopConnectionManager:
    """Stand-in for the realtime manager: `_wired_replay_bus` passes None."""

    async def push(self, *args, **kwargs) -> None: ...

    async def push_many(self, *args, **kwargs) -> None: ...


def _wired_replay_bus():
    from src.events.factory import WorkflowRegistry
    from src.workflows import build_workflows
    from tests.bus_doubles import ReplayBus

    bus = ReplayBus()
    registry = WorkflowRegistry(bus)
    build_workflows(registry, bus, _NoopConnectionManager())
    return bus, registry


async def test_redelivered_event_writes_one_audit_row(monkeypatch):
    """JetStream is at-least-once: a redelivered event must not file twice."""
    from src.events.subjects import Subjects

    async def failing_send(message):
        return False

    monkeypatch.setattr("src.email.factory.send_email", failing_send)
    bus, registry = _wired_replay_bus()
    await registry.wire()

    invitation_id = await _publish_failed_invitation(bus)
    assert len(await _email_failed_rows(invitation_id)) == 1

    await bus.redeliver(Subjects.WORKSPACE_INVITATION_CREATED)
    assert len(await _email_failed_rows(invitation_id)) == 1


async def test_redelivered_notification_event_writes_one_row_and_one_audit_row():
    """A handler that creates a row per run must not multiply either row.

    `notification.email_failed` is keyed on the notification id, so a
    redelivery that inserted a second notification row would also file a
    second audit row for the same source event.
    """
    from src.events.subjects import Subjects
    from src.models.core import Notification
    from src.services.notifications import NotificationService

    user_id = str(uuid.uuid4())
    async with SessionFactory() as session:
        await NotificationService(session).upsert_channels(
            user_id, {"workspace_invitation": "email"}
        )

    bus, registry = _wired_replay_bus()
    await registry.wire()
    await bus.publish(
        Subjects.WORKSPACE_MEMBER_INVITED,
        {
            "user_id": user_id,  # no user row: the send fails as `no_recipient`
            "workspace_id": str(uuid.uuid4()),
            "workspace_name": "Acme Corp",
            "invitation_id": str(uuid.uuid4()),
            "invited_by": "Owner",
        },
    )

    async def notifications() -> list[str]:
        async with SessionFactory() as session:
            result = await session.execute(
                select(Notification.id).where(
                    Notification.user_id == user_id,
                    Notification.type == "workspace_invitation",
                )
            )
            return list(result.scalars().all())

    (notification_id,) = await notifications()

    async def failed_rows() -> list[AuditLogEntry]:
        async with SessionFactory() as session:
            result = await session.execute(
                select(AuditLogEntry).where(
                    AuditLogEntry.action == "notification.email_failed",
                    AuditLogEntry.resource_id == notification_id,
                )
            )
            return list(result.scalars().all())

    assert len(await failed_rows()) == 1

    await bus.redeliver(Subjects.WORKSPACE_MEMBER_INVITED)
    assert await notifications() == [notification_id]
    assert len(await failed_rows()) == 1


async def test_redelivered_conversation_event_writes_one_pointer_per_recipient():
    """The bulk path is on the same path: a redelivery adds no second row."""
    from src.events.subjects import Subjects
    from src.models.core import Notification

    workspace_id = str(uuid.uuid4())
    participants = [str(uuid.uuid4()) for _ in range(3)]

    async def pointers() -> int:
        async with SessionFactory() as session:
            result = await session.execute(
                select(Notification.id).where(
                    Notification.workspace_id == workspace_id,
                    Notification.type == "conversation_message",
                )
            )
            return len(list(result.scalars().all()))

    bus, registry = _wired_replay_bus()
    await registry.wire()
    await bus.publish(
        Subjects.CONVERSATION_MESSAGE_CREATED,
        {
            "workspace_id": workspace_id,
            "conversation_id": str(uuid.uuid4()),
            "sender_id": participants[0],
            "sender_type": "user",
            "participant_user_ids": participants,
            "title": "Hi",
        },
    )
    assert await pointers() == 2  # the sender gets no pointer

    await bus.redeliver(Subjects.CONVERSATION_MESSAGE_CREATED)
    assert await pointers() == 2


async def test_repeated_participant_id_writes_one_pointer():
    """A publisher that repeats a participant id still yields one pointer."""
    from src.events.subjects import Subjects
    from src.models.core import Notification

    workspace_id = str(uuid.uuid4())
    participants = [str(uuid.uuid4()) for _ in range(2)]

    async def pointers() -> int:
        async with SessionFactory() as session:
            result = await session.execute(
                select(Notification.id).where(
                    Notification.workspace_id == workspace_id,
                    Notification.type == "conversation_message",
                )
            )
            return len(list(result.scalars().all()))

    bus, registry = _wired_replay_bus()
    await registry.wire()
    await bus.publish(
        Subjects.CONVERSATION_MESSAGE_CREATED,
        {
            "workspace_id": workspace_id,
            "conversation_id": str(uuid.uuid4()),
            "sender_id": participants[0],
            "sender_type": "user",
            "participant_user_ids": [participants[0], participants[1], participants[1]],
            "title": "Hi",
        },
    )
    assert await pointers() == 1  # the sender gets no pointer, the repeat none

    await bus.redeliver(Subjects.CONVERSATION_MESSAGE_CREATED)
    assert await pointers() == 1


async def test_create_many_logs_the_recipients_a_redelivery_drops(caplog):
    """The bulk return value counts created rows only, so a drop is silent
    unless the service says so. Its only caller discards the return value,
    so the log line is the signal."""
    import logging

    from src.services.notifications import NotificationService

    workspace_id = str(uuid.uuid4())
    source_event_id = str(uuid.uuid4())
    recipients = [str(uuid.uuid4()) for _ in range(2)]

    def specs() -> list[dict]:
        return [
            {
                "user_id": uid,
                "workspace_id": workspace_id,
                "type": "conversation_message",
                "title": "Hi",
                "body": "",
                "metadata": None,
            }
            for uid in recipients
        ]

    def records():
        return [r for r in caplog.records if r.name == "src.services.notifications"]

    with caplog.at_level(logging.INFO, logger="src.services.notifications"):
        async with SessionFactory() as session:
            assert (
                len(
                    await NotificationService(session).create_many(
                        specs(), source_event_id=source_event_id
                    )
                )
                == 2
            )
        assert not records()  # nothing dropped, nothing logged

        async with SessionFactory() as session:
            # Retention can purge one recipient's row between deliveries, so the
            # redelivery is partial: one recipient is re-notified, one is new.
            assert (
                len(
                    await NotificationService(session).create_many(
                        [specs()[0], {**specs()[1], "user_id": str(uuid.uuid4())}],
                        source_event_id=source_event_id,
                        correlation_id="corr-1205",
                    )
                )
                == 1
            )

        async with SessionFactory() as session:
            assert (
                await NotificationService(session).create_many(
                    specs(), source_event_id=source_event_id
                )
                == []
            )

    partial, full = records()
    assert source_event_id in partial.getMessage()
    assert source_event_id in full.getMessage()
    assert "corr-1205" in partial.getMessage()
    assert "correlation -" in full.getMessage()
    assert "dropped 1 of 2" in partial.getMessage()
    assert "dropped 2 of 2" in full.getMessage()


async def test_two_publishes_still_write_two_audit_rows(monkeypatch):
    """The negative control: a second failure is a new event, not a redelivery."""

    async def failing_send(message):
        return False

    monkeypatch.setattr("src.email.factory.send_email", failing_send)
    bus, registry = _wired_replay_bus()
    await registry.wire()

    invitation_id = await _publish_failed_invitation(bus)
    await _publish_failed_invitation(bus, invitation_id)

    assert len(await _email_failed_rows(invitation_id)) == 2


async def test_record_dedupes_on_source_event_without_touching_the_stored_row():
    from src.services.audit import AuditService

    fields = {
        "workspace_id": str(uuid.uuid4()),
        "resource_type": "invitation",
        "resource_id": str(uuid.uuid4()),
        "action": "invitation.email_failed",
        "details": {"email": "unreachable@example.com"},
    }
    async with SessionFactory() as session:
        first = await AuditService(session).record(source_event_id="evt-1", **fields)
    async with SessionFactory() as session:
        second = await AuditService(session).record(source_event_id="evt-1", **fields)
    # The stored row comes back untouched: same id, same created_at, same details.
    async with SessionFactory() as session:
        stored = await session.get(AuditLogEntry, first.id)
    assert second.id == first.id == stored.id
    assert second.created_at == stored.created_at
    assert stored.details == first.details
    assert first.details["source_event_id"] == "evt-1"

    async with SessionFactory() as session:
        third = await AuditService(session).record(source_event_id="evt-2", **fields)
    assert third.id != first.id

    # Without a source event there is nothing to dedupe on: every call is a row.
    for _ in range(2):
        async with SessionFactory() as session:
            await AuditService(session).record(**fields)
    async with SessionFactory() as session:
        result = await session.execute(select(AuditLogEntry))
        assert len([r for r in result.scalars() if not r.details.get("source_event_id")]) == 2


async def test_dedupe_lookup_orders_a_created_at_tie_on_id():
    """The dedupe read must be a total order, like `list_for_resource` (#1130).

    Two rows for one source event are the race `record`'s ponytail documents,
    and they share a `created_at` whenever the redelivery wins the insert
    fast. Ordering on `created_at` alone leaves which of them `record` returns
    up to the planner. The tied rows are inserted high-id-first so rowid order
    (the pre-fix read) disagrees with id order; only the `id` tiebreaker
    returns the low id.
    """
    from src.events.bus import SOURCE_EVENT_KEY
    from src.services.audit import AuditService

    fields = {
        "workspace_id": None,
        "resource_type": "invitation",
        "resource_id": str(uuid.uuid4()),
        "action": "invitation.email_failed",
    }
    low, high = (f"00000000-0000-4000-8000-00000000000{i}" for i in (1, 2))
    async with SessionFactory() as session:
        session.add_all(
            [
                AuditLogEntry(
                    id=id_,
                    details={"email": "unreachable@example.com", SOURCE_EVENT_KEY: "evt-tie"},
                    created_at=datetime(2026, 1, 1, tzinfo=UTC),
                    **fields,
                )
                for id_ in (high, low)
            ]
        )
        await session.commit()

    async with SessionFactory() as session:
        found = await AuditService(session).record(source_event_id="evt-tie", **fields)
    assert found.id == low


def test_every_workflow_audit_publish_carries_a_source_event_id():
    """Pin the opt-in the dedupe depends on.

    `on_audit_entry` falls back to the audit envelope's own event_id, which is
    correct for a direct producer and useless for a subscriber: the duplicate
    is created by the *handler* re-running, so the identity to keep is the
    inbound event's id. Every `publish_audit(` in a workflow therefore has to
    name it, and so does every `_create_notification(`: a notification
    re-inserted on redelivery is what duplicates `notification.email_failed`.
    """
    pinned = {"publish_audit", "_create_notification"}
    missing = [
        node.lineno
        for node in ast.walk(ast.parse(WORKFLOWS.read_text()))
        if isinstance(node, ast.Call)
        and (
            (isinstance(node.func, ast.Name) and node.func.id in pinned)
            or (isinstance(node.func, ast.Attribute) and node.func.attr in pinned)
        )
        and not any(kw.arg == "source_event_id" for kw in node.keywords)
    ]
    assert not missing, f"{sorted(pinned)} without source_event_id at lines {missing}"
