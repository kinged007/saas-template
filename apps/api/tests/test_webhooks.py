"""Outbound webhooks: signing, filtering, dispatch, retry, API isolation."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid

import httpx

from src.db.session import SessionFactory
from src.events.subjects import Subjects
from src.models.webhook import WebhookDeliveryStatus
from src.services.webhooks import (
    MAX_ATTEMPTS,
    WebhookService,
    deliver_once,
    dispatch_due,
    fan_out_event,
    next_retry_delay,
    sign_payload,
    verify_signature,
)


def test_sign_verify_round_trip():
    body = b'{"event":"member.joined"}'
    sig = sign_payload("secret", "123", body)
    assert sig.startswith("sha256=")
    assert verify_signature("secret", "123", body, sig)
    assert not verify_signature("secret", "123", body, "sha256=deadbeef")
    # Matches a manual HMAC computation over timestamp + "." + raw body.
    expected = hmac.new(b"secret", b"123." + body, hashlib.sha256).hexdigest()
    assert sig == f"sha256={expected}"


def test_backoff_schedule():
    assert next_retry_delay(1) == 60
    assert next_retry_delay(2) == 300
    assert next_retry_delay(3) == 1800
    assert next_retry_delay(4) == 7200
    assert next_retry_delay(5) == 43200
    assert next_retry_delay(6) is None  # exhausted after MAX_ATTEMPTS
    assert MAX_ATTEMPTS == 6


WS1 = str(uuid.uuid4())
WS2 = str(uuid.uuid4())
WS3 = str(uuid.uuid4())
WS4 = str(uuid.uuid4())


async def _service(app):
    from src.container import Container

    assert isinstance(app.state.container, Container)
    store = app.state.container.secret_store
    session = SessionFactory()
    return session, WebhookService(session, store)


async def _deliveries(session, workspace_id):
    from sqlalchemy import select

    from src.models.webhook import WebhookDelivery

    rows = await session.execute(
        select(WebhookDelivery).where(WebhookDelivery.workspace_id == workspace_id)
    )
    return list(rows.scalars().all())


async def test_enqueue_filters_by_event(app):
    session, service = await _service(app)
    try:
        sub, _ = await service.create_subscription(
            WS1, url="https://example.com/hook", events=["member.joined"]
        )
        n = await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_JOINED,
            payload={"workspace_id": WS1, "user_id": "u"},
            event_id="e1",
            correlation_id=None,
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        assert n == 1
        n = await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_REMOVED,
            payload={"workspace_id": WS1, "user_id": "u"},
            event_id="e2",
            correlation_id=None,
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        assert n == 0
        deliveries = await _deliveries(session, WS1)
        assert len(deliveries) == 1
        assert deliveries[0].event_type == "member.joined"
        assert deliveries[0].payload["event"] == "member.joined"
        assert deliveries[0].payload["event_id"] == "e1"
        assert sub.id == deliveries[0].subscription_id
    finally:
        await session.close()


async def test_fan_out_carries_correlation_id_into_payload(app):
    session, service = await _service(app)
    try:
        await service.create_subscription(
            WS1, url="https://example.com/hook", events=["member.role_changed"]
        )
        n = await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_ROLE_CHANGED,
            payload={"workspace_id": WS1, "user_id": "u"},
            event_id="corr-e1",
            correlation_id="corr-1",
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        assert n == 1
        deliveries = await _deliveries(session, WS1)
        assert len(deliveries) == 1
        row = deliveries[0]
        assert row is not None
        assert row.correlation_id == "corr-1"
        assert row.payload["correlation_id"] == "corr-1"
        assert row.payload["event_id"] == "corr-e1"
        # Uncorrelated publishes fan out without one (empty string bus
        # default normalizes to None), not as an empty body field.
        n = await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_ROLE_CHANGED,
            payload={"workspace_id": WS1, "user_id": "u"},
            event_id="corr-e2",
            correlation_id="",
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        assert n == 1
        deliveries = await _deliveries(session, WS1)
        assert len(deliveries) == 2
        unmatched = next(d for d in deliveries if d.event_id == "corr-e2")
        assert unmatched is not None
        assert unmatched.correlation_id is None
        assert unmatched.payload["correlation_id"] is None
    finally:
        await session.close()


async def test_transfer_produces_two_paired_role_changed_deliveries(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="wh-owner@example.com")
    await register_user(app_client, email="wh-heir@example.com")
    owner = await login(app_client, email="wh-owner@example.com")
    heir = await login(app_client, email="wh-heir@example.com")

    async def _user_id(tokens) -> str:
        resp = await app_client.get(
            "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
        )
        assert resp.status_code == 200, resp.text
        return resp.json()["id"]

    owner_id, heir_id = await _user_id(owner), await _user_id(heir)
    ws = await create_workspace(app_client, owner, name="WH Transfer")
    wid = ws["id"]

    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://example.com/hook", "events": ["member.role_changed"]},
        headers=ws_headers(owner, wid),
    )
    assert resp.status_code == 201, resp.text

    resp = await app_client.get("/api/v1/roles", headers=ws_headers(owner, wid))
    assert resp.status_code == 200, resp.text
    roles = {r["name"]: r["id"] for r in resp.json()}
    resp = await app_client.post(
        "/api/v1/invitations",
        json={"email": "wh-heir@example.com", "role_id": roles["admin"]},
        headers=ws_headers(owner, wid),
    )
    assert resp.status_code == 201, resp.text
    resp = await app_client.post(
        f"/api/v1/invitations/accept?token={resp.json()['token']}",
        headers={"Authorization": f"Bearer {heir['access_token']}"},
    )
    assert resp.status_code == 200, resp.text

    resp = await app_client.get("/api/v1/members", headers=ws_headers(owner, wid))
    assert resp.status_code == 200, resp.text
    heir_row = next(m for m in resp.json() if m["email"] == "wh-heir@example.com")
    assert heir_row is not None
    resp = await app_client.post(
        f"/api/v1/workspaces/{wid}/transfer",
        json={"new_owner_membership_id": heir_row["membership_id"]},
        headers=ws_headers(owner, wid),
    )
    assert resp.status_code == 200, resp.text

    async def _role_changed_deliveries():
        resp = await app_client.get(
            "/api/v1/webhooks/deliveries",
            headers=ws_headers(owner, wid),
        )
        assert resp.status_code == 200, resp.text
        return [d for d in resp.json() if d["event_type"] == "member.role_changed"]

    deliveries = []
    for _ in range(150):
        deliveries = await _role_changed_deliveries()
        if len(deliveries) == 2:
            break
        await asyncio.sleep(0.02)
    assert len(deliveries) == 2
    # One delivery per affected user: the promoted heir and the demoted owner.
    by_user = {d["payload"]["data"]["user_id"]: d for d in deliveries}
    assert set(by_user) == {heir_id, owner_id}
    assert by_user[heir_id]["payload"]["data"]["to_role"] == "owner"
    correlation_ids = {d["correlation_id"] for d in deliveries}
    assert len(correlation_ids) == 1
    correlation_id = next(iter(correlation_ids))
    assert correlation_id
    assert all(d["payload"]["correlation_id"] == correlation_id for d in deliveries)


async def test_dispatch_success_with_mock_transport(app):
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    session, service = await _service(app)
    try:
        sub, secret = await service.create_subscription(
            WS2, url="https://example.com/hook", events=["member.joined"]
        )
        await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_JOINED,
            payload={"workspace_id": WS2},
            event_id="e9",
            correlation_id=None,
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            assert await dispatch_due(session, service._secrets, client=client) == 1
        deliveries = await _deliveries(session, WS2)
        assert deliveries[0].status == WebhookDeliveryStatus.SUCCESS
        assert deliveries[0].attempt_count == 1
        headers = seen["headers"]
        assert headers["x-webhook-event"] == "member.joined"
        assert headers["x-webhook-delivery"] == deliveries[0].id
        assert verify_signature(
            secret,
            headers["x-webhook-timestamp"],
            seen["body"],
            headers["x-webhook-signature"],
        )
        envelope = json.loads(seen["body"])
        assert envelope["event"] == "member.joined"
        assert envelope["workspace_id"] == WS2
        assert sub.id == deliveries[0].subscription_id
    finally:
        await session.close()


async def test_retry_then_exhaustion(app):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"err": True})

    session, service = await _service(app)
    try:
        await service.create_subscription(
            WS3, url="https://example.com/hook", events=["member.joined"]
        )
        await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_JOINED,
            payload={"workspace_id": WS3},
            event_id="ex",
            correlation_id=None,
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            for _ in range(MAX_ATTEMPTS):
                delivery = (await _deliveries(session, WS3))[0]
                # Fast-forward past the scheduled retry.
                from datetime import timedelta

                from src.core.dates import now_utc

                delivery.next_retry_at = now_utc() - timedelta(seconds=1)
                await session.commit()
                await dispatch_due(session, service._secrets, client=client)
        delivery = (await _deliveries(session, WS3))[0]
        assert delivery.status == WebhookDeliveryStatus.EXHAUSTED
        assert delivery.attempt_count == MAX_ATTEMPTS
        assert delivery.next_retry_at is None
    finally:
        await session.close()


async def test_deliver_once_signs_envelope():
    from src.models.webhook import WebhookDelivery

    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["headers"] = dict(request.headers)
        seen["body"] = request.content
        return httpx.Response(200, json={"ok": True})

    delivery = WebhookDelivery(
        id=str(uuid.uuid4()),
        subscription_id=str(uuid.uuid4()),
        workspace_id=WS1,
        event_type="member.joined",
        subject=Subjects.WORKSPACE_MEMBER_JOINED,
        payload={"event": "member.joined"},
    )
    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as client:
        ok, status_code, error = await deliver_once(
            delivery, "https://example.com/hook", "s3cret", client=client
        )
    assert (ok, status_code, error) == (True, 200, None)
    assert verify_signature(
        "s3cret",
        seen["headers"]["x-webhook-timestamp"],
        seen["body"],
        seen["headers"]["x-webhook-signature"],
    )


async def test_api_permission_isolation(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="wh1@example.com")
    tokens = await login(app_client, email="wh1@example.com")
    ws = await create_workspace(app_client, tokens, name="WH One")
    wid = ws["id"]

    await register_user(app_client, email="wh2@example.com")
    tokens2 = await login(app_client, email="wh2@example.com")
    ws2 = await create_workspace(app_client, tokens2, name="WH Two")

    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://example.com/hook", "events": ["member.joined"]},
        headers=ws_headers(tokens, wid),
    )
    assert resp.status_code == 201, resp.text
    sub_id = resp.json()["id"]
    assert resp.json()["secret"]

    # Cross-workspace id 404s (never 403) so callers cannot probe existence.
    resp = await app_client.get(
        f"/api/v1/webhooks/subscriptions/{sub_id}/deliveries",
        headers=ws_headers(tokens2, ws2["id"]),
    )
    assert resp.status_code == 404

    # Unknown event rejected.
    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://example.com/hook", "events": ["nope.event"]},
        headers=ws_headers(tokens, wid),
    )
    assert resp.status_code == 422

    # Events catalog lists registry names.
    resp = await app_client.get("/api/v1/webhooks/events", headers=ws_headers(tokens, wid))
    assert resp.status_code == 200
    assert "member.joined" in resp.json()["events"]


async def test_get_subscription_by_id(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="whget1@example.com")
    tokens = await login(app_client, email="whget1@example.com")
    ws = await create_workspace(app_client, tokens, name="WH Get One")
    wid = ws["id"]

    await register_user(app_client, email="whget2@example.com")
    tokens2 = await login(app_client, email="whget2@example.com")
    ws2 = await create_workspace(app_client, tokens2, name="WH Get Two")

    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://example.com/hook", "events": ["member.joined"]},
        headers=ws_headers(tokens, wid),
    )
    assert resp.status_code == 201, resp.text
    sub_id = resp.json()["id"]

    body = (
        await app_client.get(
            f"/api/v1/webhooks/subscriptions/{sub_id}", headers=ws_headers(tokens, wid)
        )
    ).json()
    assert body["id"] == sub_id
    assert body["workspace_id"] == wid
    assert body["url"] == "https://example.com/hook"
    assert body["events"] == ["member.joined"]
    assert body["active"] is True
    assert "created_at" in body and "updated_at" in body
    # The signing secret is minted only on create/rotate; a plain read must
    # never carry it (or any key-like field).
    assert "secret" not in body
    assert "_signing_key" not in body

    # Cross-workspace id 404s (never 403) so callers cannot probe existence.
    resp = await app_client.get(
        f"/api/v1/webhooks/subscriptions/{sub_id}", headers=ws_headers(tokens2, ws2["id"])
    )
    assert resp.status_code == 404

    resp = await app_client.get(
        f"/api/v1/webhooks/subscriptions/{uuid.uuid4()}", headers=ws_headers(tokens, wid)
    )
    assert resp.status_code == 404

    # Malformed (non-UUID) id 404s too, not 500, so callers cannot probe
    # route shape by id validity.
    resp = await app_client.get(
        "/api/v1/webhooks/subscriptions/not-a-uuid", headers=ws_headers(tokens, wid)
    )
    assert resp.status_code == 404, resp.text

    # Delivery-id lookups get the same treatment: malformed id 404s, not 500.
    resp = await app_client.get(
        "/api/v1/webhooks/deliveries/not-a-uuid", headers=ws_headers(tokens, wid)
    )
    assert resp.status_code == 404, resp.text
    resp = await app_client.post(
        "/api/v1/webhooks/deliveries/not-a-uuid/redeliver", headers=ws_headers(tokens, wid)
    )
    assert resp.status_code == 404, resp.text


async def test_private_url_rejected(app_client):
    from tests.conftest import create_workspace, login, register_user, ws_headers

    await register_user(app_client, email="wh3@example.com")
    tokens = await login(app_client, email="wh3@example.com")
    ws = await create_workspace(app_client, tokens, name="WH Three")
    resp = await app_client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "http://127.0.0.1/hook", "events": ["member.joined"]},
        headers=ws_headers(tokens, ws["id"]),
    )
    assert resp.status_code == 422


async def test_redeliver_resets_failed(app):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"err": True})

    session, service = await _service(app)
    try:
        await service.create_subscription(
            WS4, url="https://example.com/hook", events=["member.joined"]
        )
        await fan_out_event(
            session,
            subject=Subjects.WORKSPACE_MEMBER_JOINED,
            payload={"workspace_id": WS4},
            event_id="rd",
            correlation_id=None,
            occurred_at="2026-01-01T00:00:00+00:00",
        )
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            await dispatch_due(session, service._secrets, client=client)
        delivery = (await _deliveries(session, WS4))[0]
        assert delivery.status == WebhookDeliveryStatus.PENDING
        assert delivery.next_retry_at is not None
        redelivered = await service.redeliver(WS4, delivery.id)
        assert redelivered.status == WebhookDeliveryStatus.PENDING
        assert redelivered.next_retry_at is not None
    finally:
        await session.close()
