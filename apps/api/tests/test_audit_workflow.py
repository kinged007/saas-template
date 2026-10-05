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

import yaml
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry

COMPOSE = Path(__file__).resolve().parents[3] / "infra/docker/docker-compose.prod.yml"
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
        assert "dropped" not in caplog.text  # nothing dropped, nothing logged

        async with SessionFactory() as session:
            assert (
                await NotificationService(session).create_many(
                    specs(), source_event_id=source_event_id
                )
                == []
            )

    assert source_event_id in caplog.text
    assert "dropped 2 of 2" in caplog.text


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
