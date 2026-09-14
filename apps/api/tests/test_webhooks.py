"""Outbound webhooks: signing, backoff, fan-out, retry exhaustion, API isolation."""

from __future__ import annotations

import asyncio
import inspect
import json

import httpx
import pytest
from sqlalchemy import select

from src.db.session import SessionFactory
from src.events.bus import EventMetadata
from src.events.subjects import Subjects
from src.events.webhook_events import webhook_event_names, webhook_subject_events
from src.models.webhook import WebhookDelivery, WebhookDeliveryStatus
from src.services.webhooks import (
    fan_out_event,
    next_retry_at,
    sign_payload,
    validate_url,
    verify_signature,
)
from tests.conftest import create_workspace, login, register_user, ws_headers


async def _wait_for(predicate, timeout_secs: float = 5.0, interval: float = 0.02) -> bool:
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


async def _deliveries(workspace_id: str) -> list[WebhookDelivery]:
    async with SessionFactory() as session:
        result = await session.execute(
            select(WebhookDelivery).where(WebhookDelivery.workspace_id == workspace_id)
        )
        return list(result.scalars().all())


def _ok_transport(seen: list, status: int = 200):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"ok": True})

    return httpx.MockTransport(handler)


# ------------------------------------------------------------------ unit

def test_sign_verify_round_trip():
    sig = sign_payload("s3cret", "123", b'{"a":1}')
    assert sig.startswith("sha256=")
    assert verify_signature("s3cret", "123", b'{"a":1}', sig)
    assert not verify_signature("other", "123", b'{"a":1}', sig)
    assert not verify_signature("s3cret", "124", b'{"a":1}', sig)


def test_backoff_schedule():
    assert next_retry_at(6) is None
    assert next_retry_at(99) is None
    from datetime import datetime
    from src.core.dates import now_utc

    base = now_utc()
    times = [next_retry_at(i, now=base) for i in range(1, 6)]
    assert all(isinstance(t, datetime) for t in times)
    gaps = [(b - a).total_seconds() for a, b in zip(times, times[1:])]  # type: ignore[operator]
    assert gaps == sorted(gaps)  # non-decreasing backoff
    assert (times[0] - base).total_seconds() == pytest.approx(60)  # type: ignore[operator]


def test_registry_excludes_transient_and_internal():
    names = set(webhook_event_names())
    assert "workspaces.created" in names
    assert "conversations.message.created" in names
    subjects = set(webhook_subject_events())
    assert Subjects.NOTIFICATIONS_CREATED not in subjects
    assert Subjects.CONVERSATION_MESSAGE_LIVE not in subjects
    assert Subjects.CONVERSATION_RENAMED not in subjects
    assert Subjects.JOBS_EXECUTE not in subjects


def test_validate_url_rejects_private_and_plain_http():
    with pytest.raises(ValueError):
        validate_url("http://example.com/hook")
    with pytest.raises(ValueError):
        validate_url("ftp://example.com/hook")
    with pytest.raises(ValueError):
        validate_url("https://10.0.0.1/hook")
    with pytest.raises(ValueError):
        validate_url("https://192.168.1.10/hook")
    # Loopback is the dev/test path (skips the DNS check); unresolvable hosts
    # pass validation and fail at delivery (logged on the delivery row).
    validate_url("http://localhost:9999/hook")
    validate_url("https://webhook.invalid/hook")


# ------------------------------------------------------------------ API

async def _setup(app_client):
    await register_user(app_client, email="wh@example.com")
    tokens = await login(app_client, email="wh@example.com")
    ws = await create_workspace(app_client, tokens, name="WH Corp")
    return tokens, ws["id"]


async def test_crud_and_event_filtering(app_client):
    tokens, ws_id = await _setup(app_client)
    headers = ws_headers(tokens, ws_id)

    resp = await app_client.get("/api/v1/webhooks/events", headers=headers)
    assert resp.status_code == 200, resp.text
    assert "workspaces.created" in resp.json()["events"]

    # Unknown event rejected
    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://webhook.invalid/hook", "events": ["nope.event"]},
        headers=headers,
    )
    assert resp.status_code == 422

    # Private URL rejected
    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://192.168.0.99/hook", "events": ["apikeys.created"]},
        headers=headers,
    )
    assert resp.status_code == 422

    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://webhook.invalid/hook", "events": ["apikeys.created"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    sub_id = body["id"]
    assert body["signing_secret"]
    assert "signing_secret" not in (await app_client.get(
        f"/api/v1/webhooks/subscriptions/{sub_id}", headers=headers
    )).json()

    # Rotate returns a new secret
    resp = await app_client.post(
        f"/api/v1/webhooks/subscriptions/{sub_id}/rotate-secret", headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["signing_secret"] != body["signing_secret"]

    # Update + delete
    resp = await app_client.patch(
        f"/api/v1/webhooks/subscriptions/{sub_id}",
        json={"active": False},
        headers=headers,
    )
    assert resp.status_code == 200 and resp.json()["active"] is False
    resp = await app_client.delete(
        f"/api/v1/webhooks/subscriptions/{sub_id}", headers=headers
    )
    assert resp.status_code == 204, resp.text


async def test_cross_workspace_isolation(app_client):
    await register_user(app_client, email="wh1@example.com")
    t1 = await login(app_client, email="wh1@example.com")
    w1 = await create_workspace(app_client, t1, name="W1")
    await register_user(app_client, email="wh2@example.com")
    t2 = await login(app_client, email="wh2@example.com")
    w2 = await create_workspace(app_client, t2, name="W2")

    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://webhook.invalid/hook", "events": ["apikeys.created"]},
        headers=ws_headers(t1, w1["id"]),
    )
    assert resp.status_code == 201, resp.text
    sub_id = resp.json()["id"]

    # Other workspace sees 404, not the row
    resp = await app_client.get(
        f"/api/v1/webhooks/subscriptions/{sub_id}", headers=ws_headers(t2, w2["id"])
    )
    assert resp.status_code == 404
    resp = await app_client.get("/api/v1/webhooks/deliveries", headers=ws_headers(t2, w2["id"]))
    assert resp.status_code == 200 and resp.json() == []


async def test_fanout_signed_delivery_and_retry_exhaustion(app_client, monkeypatch):
    tokens, ws_id = await _setup(app_client)
    headers = ws_headers(tokens, ws_id)

    seen: list[httpx.Request] = []
    transport = _ok_transport(seen, status=500)
    monkeypatch.setattr(
        "src.services.webhooks.httpx.AsyncClient",
        lambda *a, **k: httpx.AsyncClient(transport=transport, timeout=10.0),
    )

    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://webhook.invalid/hook", "events": ["apikeys.created"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    secret = resp.json()["signing_secret"]

    # Trigger an apikeys.created event via the real API (bus fan-out path)
    resp = await app_client.post(
        "/api/v1/api-keys", json={"name": "k1", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text

    async def _has_delivery():
        return len(await _deliveries(ws_id)) == 1

    assert await _wait_for(_has_delivery)

    async def _attempted():
        rows = await _deliveries(ws_id)
        return rows and rows[0].attempt_count >= 1

    # Drive the dispatcher tick directly: the app loop ticks every ~10s and
    # the monkeypatched transport only applies in this test's process
    # context, so tick inline instead of waiting on the background loop.
    from src.services.webhook_dispatcher import WebhookDispatcher

    # Tick inline with the live container store (secret lookup needs the DB
    # store); the monkeypatched httpx.AsyncClient applies to the attempt.
    from src.main import app as _app
    from src.services.webhooks import dispatch_due

    store = _app.state.container.secret_store
    for _ in range(30):
        await dispatch_due(secret_store=store)
        if await _attempted():
            break
        await asyncio.sleep(0.2)
    assert await _attempted()
    delivery = (await _deliveries(ws_id))[0]
    assert delivery.event_type == "apikeys.created"
    assert delivery.status in ("failed", "success")
    assert len(seen) >= 1
    req = seen[0]
    assert req.headers["X-Webhook-Event"] == "apikeys.created"
    assert req.headers["X-Webhook-Delivery"] == delivery.id
    assert verify_signature(secret, req.headers["X-Webhook-Timestamp"], req.content, req.headers["X-Webhook-Signature"])
    envelope = json.loads(req.content)
    assert envelope["event"] == "apikeys.created"
    assert envelope["workspace_id"] == ws_id

    # Force exhaustion through repeated failing attempts
    from src.core.dates import now_utc
    from src.services.webhooks import dispatch_delivery

    async with SessionFactory() as session:
        row = await session.get(WebhookDelivery, delivery.id)
        row.status = WebhookDeliveryStatus.FAILED
        row.next_retry_at = now_utc()
        await session.commit()
    for _ in range(6):
        async with SessionFactory() as session:
            row = await session.get(WebhookDelivery, delivery.id)
            row.next_retry_at = now_utc()
            await session.commit()
        await dispatch_delivery(delivery.id)
    async with SessionFactory() as session:
        final = await session.get(WebhookDelivery, delivery.id)
        assert final.status == WebhookDeliveryStatus.EXHAUSTED
        assert final.next_retry_at is None

    # Delivery log visible + redeliver resets to pending
    resp = await app_client.get("/api/v1/webhooks/deliveries", headers=headers)
    assert resp.status_code == 200 and len(resp.json()) == 1
    resp = await app_client.post(
        f"/api/v1/webhooks/deliveries/{delivery.id}/redeliver", headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["status"] in ("pending", "failed", "success")


async def test_fanout_success_path_with_mock_transport():
    from src.db.session import engine
    from src import models as _m  # noqa: F401
    from src.db.base import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        from sqlalchemy import select as _select

        from src.models.workspace import User, Workspace, WorkspaceMember, Role

        async with SessionFactory() as session:
            user = User(email="fan@example.com", display_name="Fan", password_hash="x")
            session.add(user)
            await session.flush()
            ws = Workspace(name="Fan", slug="fan", created_by_user_id=user.id)
            session.add(ws)
            await session.flush()
            role = Role(workspace_id=ws.id, name="owner", permissions=["*"], system=False)
            session.add(role)
            await session.flush()
            session.add(WorkspaceMember(workspace_id=ws.id, user_id=user.id, role_id=role.id, status="active"))
            from src.models.webhook import WebhookSubscription as _Sub

            sub = _Sub(workspace_id=ws.id, url="https://webhook.invalid/hook", events=["audit.entry.created"], active=True)
            session.add(sub)
            await session.commit()
            ws_id, sub_id = ws.id, sub.id

        seen: list[httpx.Request] = []
        client = httpx.AsyncClient(transport=_ok_transport(seen, status=200))
        n = await fan_out_event(
            Subjects.AUDIT_ENTRY_CREATED,
            {"workspace_id": ws_id, "action": "x"},
            EventMetadata(subject=Subjects.AUDIT_ENTRY_CREATED),
            client=client,
        )
        assert n == 1
        assert len(seen) == 1
        async with SessionFactory() as session:
            rows = (
                await session.execute(
                    _select(WebhookDelivery).where(WebhookDelivery.subscription_id == sub_id)
                )
            ).scalars().all()
            assert len(rows) == 1
            assert rows[0].status == WebhookDeliveryStatus.SUCCESS
    finally:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
