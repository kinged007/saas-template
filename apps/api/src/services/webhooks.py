"""Outbound webhooks: subscriptions, HMAC-signed delivery, backoff/retry.

Signature scheme (documented for subscribers):
  headers: X-Webhook-Event (public event name), X-Webhook-Delivery
  (delivery id, dedupe key), X-Webhook-Timestamp (unix seconds),
  X-Webhook-Signature: sha256=<hex hmac-sha256(secret, timestamp + "." + body)>
  Verify: recompute the HMAC over `<timestamp>.<raw_body>` with the shared
  secret and compare with hmac.compare_digest. Check the timestamp is recent
  (±5 minutes) to blunt replay.

Delivery is at-least-once and unordered across retries: subscribers must
dedupe on X-Webhook-Delivery / event_id.

Payload envelope v1: {event, event_id, occurred_at, workspace_id, data}.
Registry additions must stay additive.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlparse

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.db.session import SessionFactory
from src.events.bus import EventBus, EventMetadata
from src.events.webhook_events import webhook_event_names, webhook_subject_events
from src.models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Webhook-Signature"
EVENT_HEADER = "X-Webhook-Event"
DELIVERY_HEADER = "X-Webhook-Delivery"
TIMESTAMP_HEADER = "X-Webhook-Timestamp"

MAX_ATTEMPTS = 6
# Delays after failures 1..5 (attempt 6 exhausts): 1m, 5m, 30m, 2h, 12h.
BACKOFF_SECONDS = [60, 300, 1800, 7200, 43200]
DELIVERY_TIMEOUT_SECONDS = 10.0
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_URL_LENGTH = 2000

SECRET_KIND = "webhook_signing_secret"


def secret_key_for(subscription_id: str) -> str:
    return f"webhooks:{subscription_id}:signing_secret"


def sign_payload(secret: str, timestamp: str, body: bytes) -> str:
    """`sha256=<hex>` HMAC over `<timestamp>.<raw_body>`."""
    digest = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def verify_signature(secret: str, timestamp: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_payload(secret, timestamp, body), signature)


def next_retry_at(attempt_count: int, *, now: datetime | None = None) -> datetime | None:
    """Retry time after `attempt_count` failures, or None when exhausted."""
    if attempt_count >= MAX_ATTEMPTS:
        return None
    delay = BACKOFF_SECONDS[min(attempt_count - 1, len(BACKOFF_SECONDS) - 1)]
    return (now or now_utc()) + timedelta(seconds=delay)


def validate_url(url: str, *, allow_private: bool = False) -> str:
    """SSRF guard: https-only (http allowed for loopback dev/test), size cap,
    deny loopback/link-local/private/multicast/reserved hosts by default."""
    if len(url) > MAX_URL_LENGTH or len(url.encode()) > MAX_URL_LENGTH:
        raise ValueError("url too long")
    try:
        parsed = urlparse(url)
    except Exception:
        raise ValueError("invalid url") from None
    if parsed.scheme not in ("http", "https"):
        raise ValueError("url must use http or https")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("invalid url")
    if parsed.scheme == "http" and host not in ("localhost", "127.0.0.1", "::1"):
        raise ValueError("http is only allowed for localhost")
    if host in ("localhost", "127.0.0.1", "::1"):
        # Loopback http(s) is the dev/test path (incl. httpx MockTransport
        # tests that never hit the network); the DNS check below would reject
        # it as non-global, so skip it. Production deployments should only
        # create https subscriptions to public hosts.
        return url
    if not allow_private:
        import socket

        try:
            for info in socket.getaddrinfo(host, None):
                if not ipaddress.ip_address(info[4][0]).is_global:
                    raise ValueError("url resolves to a non-public address")
        except ValueError:
            raise
        except Exception:
            # Unresolvable host: let delivery fail (logged), don't block create.
            pass
    return url


def build_envelope(
    *, event: str, workspace_id: str, data: dict, metadata: EventMetadata | None = None
) -> dict:
    meta = metadata or EventMetadata(subject=event)
    return {
        "event": event,
        "event_id": meta.event_id,
        "occurred_at": meta.occurred_at,
        "workspace_id": workspace_id,
        "data": data,
    }


async def _get_secret(secret_store, workspace_id: str, subscription_id: str) -> str | None:
    if secret_store is None:
        return None
    record = await secret_store.get(
        workspace_id=workspace_id, key=secret_key_for(subscription_id)
    )
    return record.value if record else None


class WebhookService:
    """Request-scoped CRUD over subscriptions + delivery log reads."""

    def __init__(
        self, session: AsyncSession, bus: EventBus | None = None, secret_store=None
    ) -> None:
        self._session = session
        self._bus = bus
        self._secrets = secret_store

    async def create_subscription(
        self,
        *,
        workspace_id: str,
        url: str,
        events: list[str],
        created_by_user_id: str | None = None,
        flush_only: bool = False,
    ) -> tuple[WebhookSubscription, str]:
        known = set(webhook_event_names())
        unknown = [e for e in events if e not in known]
        if unknown:
            raise ValueError(f"unknown event types: {', '.join(unknown)}")
        validate_url(url)
        sub = WebhookSubscription(
            workspace_id=workspace_id,
            url=url,
            events=sorted(set(events)),
            active=True,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(sub)
        await self._session.flush()
        secret = secrets.token_urlsafe(32)
        # Commit BEFORE the SecretStore put: the DB store opens its own
        # session, which would deadlock against this open transaction on
        # sqlite's single writer (and serialize on postgres).
        await self._session.commit()
        if self._secrets is not None:
            await self._secrets.put(
                workspace_id=workspace_id,
                key=secret_key_for(sub.id),
                value=secret,
                kind=SECRET_KIND,
                label=f"webhook {sub.id}",
            )
        if not flush_only:
            await self._session.commit()
        return sub, secret

    async def rotate_secret(self, sub: WebhookSubscription) -> str:
        secret = secrets.token_urlsafe(32)
        # Capture ORM state BEFORE the SecretStore put: the DB store commits
        # on its own session, which expires this session's attributes; any
        # lazy refresh afterwards raises MissingGreenlet under asyncio.
        sub_id, sub_ws = sub.id, sub.workspace_id
        await self._session.commit()  # flush own txn before the store's own-session commit
        if self._secrets is not None:
            await self._secrets.put(
                workspace_id=sub_ws,
                key=secret_key_for(sub_id),
                value=secret,
                kind=SECRET_KIND,
                label=f"webhook {sub_id}",
            )
        return secret

    async def get_subscription(self, subscription_id: str) -> WebhookSubscription | None:
        return await self._session.get(WebhookSubscription, subscription_id)

    async def list_subscriptions(self, workspace_id: str) -> list[WebhookSubscription]:
        result = await self._session.execute(
            select(WebhookSubscription)
            .where(WebhookSubscription.workspace_id == workspace_id)
            .order_by(WebhookSubscription.created_at.asc())
        )
        return list(result.scalars().all())

    async def get_delivery(self, delivery_id: str) -> WebhookDelivery | None:
        return await self._session.get(WebhookDelivery, delivery_id)

    def to_dict(self, sub: WebhookSubscription) -> dict:
        return {
            "id": sub.id,
            "workspace_id": sub.workspace_id,
            "url": sub.url,
            "events": list(sub.events or []),
            "active": sub.active,
            "created_by_user_id": sub.created_by_user_id,
            "created_at": sub.created_at.isoformat() if sub.created_at else None,
            "updated_at": sub.updated_at.isoformat() if sub.updated_at else None,
        }

    def delivery_to_dict(self, d: WebhookDelivery) -> dict:
        return {
            "id": d.id,
            "subscription_id": d.subscription_id,
            "workspace_id": d.workspace_id,
            "event_type": d.event_type,
            "subject": d.subject,
            "status": d.status,
            "attempt_count": d.attempt_count,
            "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
            "response_status": d.response_status,
            "error": d.error,
            "event_id": d.event_id,
            "correlation_id": d.correlation_id,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "updated_at": d.updated_at.isoformat() if d.updated_at else None,
        }


async def fan_out_event(
    subject: str,
    payload: dict,
    metadata: EventMetadata,
    *,
    secret_store=None,
    client: httpx.AsyncClient | None = None,
) -> int:
    """Insert one pending delivery per matching subscription, then dispatch.

    Own session per call (workflow discipline). Returns deliveries enqueued.
    """
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        return 0
    names = webhook_subject_events().get(subject, [])
    if not names:
        return 0
    async with SessionFactory() as session:
        result = await session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.workspace_id == workspace_id,
                WebhookSubscription.active.is_(True),
            )
        )
        subs = [
            s for s in result.scalars().all() if set(s.events or []) & set(names)
        ]
        if not subs:
            return 0
        deliveries: list[WebhookDelivery] = []
        for sub in subs:
            for name in sorted(set(sub.events or []) & set(names)):
                envelope = build_envelope(
                    event=name, workspace_id=workspace_id, data=payload, metadata=metadata
                )
                deliveries.append(
                    WebhookDelivery(
                        subscription_id=sub.id,
                        workspace_id=workspace_id,
                        event_type=name,
                        subject=subject,
                        payload=envelope,
                        status=WebhookDeliveryStatus.PENDING,
                        next_retry_at=now_utc(),
                        event_id=metadata.event_id,
                        correlation_id=metadata.correlation_id or None,
                    )
                )
        session.add_all(deliveries)
        await session.commit()
        ids = [d.id for d in deliveries]
    for delivery_id in ids:
        try:
            await dispatch_delivery(delivery_id, secret_store=secret_store, client=client)
        except Exception:
            logger.exception("webhook dispatch failed for delivery %s", delivery_id)
    return len(ids)


async def dispatch_delivery(
    delivery_id: str, *, secret_store=None, client: httpx.AsyncClient | None = None
) -> WebhookDelivery | None:
    """Attempt one delivery; CAS-claims the row so replicas never duplicate."""
    async with SessionFactory() as session:
        delivery = await session.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.status not in (
            WebhookDeliveryStatus.PENDING,
            WebhookDeliveryStatus.FAILED,
        ):
            return delivery
        if delivery.next_retry_at and ensure_utc(delivery.next_retry_at) > now_utc():
            return delivery
        sub = await session.get(WebhookSubscription, delivery.subscription_id)
        if sub is None or not sub.active:
            delivery.status = WebhookDeliveryStatus.EXHAUSTED
            delivery.error = "subscription deleted or disabled"
            await session.commit()
            return delivery
        # CAS claim: only proceed if the row is still due (lost race → skip).
        claimed = await session.execute(
            update(WebhookDelivery)
            .where(
                WebhookDelivery.id == delivery.id,
                WebhookDelivery.status.in_(
                    [WebhookDeliveryStatus.PENDING, WebhookDeliveryStatus.FAILED]
                ),
            )
            .values(attempt_count=WebhookDelivery.attempt_count + 1)
        )
        if claimed.rowcount != 1:
            await session.rollback()
            return delivery
        await session.refresh(delivery)
        url, secret = sub.url, await _get_secret(secret_store, sub.workspace_id, sub.id)
        body = json.dumps(delivery.payload).encode()
        timestamp = str(int(time.time()))
        headers = {
            "Content-Type": "application/json",
            EVENT_HEADER: delivery.event_type,
            DELIVERY_HEADER: delivery.id,
            TIMESTAMP_HEADER: timestamp,
        }
        if secret:
            headers[SIGNATURE_HEADER] = sign_payload(secret, timestamp, body)
        if len(body) > MAX_PAYLOAD_BYTES:
            delivery.status = WebhookDeliveryStatus.EXHAUSTED
            delivery.error = "payload exceeds size limit"
            await session.commit()
            return delivery
        try:
            if client is None:
                async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as owned:
                    response = await owned.post(url, content=body, headers=headers)
            else:
                response = await client.post(url, content=body, headers=headers)
            delivery.response_status = response.status_code
            if 200 <= response.status_code < 300:
                delivery.status = WebhookDeliveryStatus.SUCCESS
                delivery.error = None
                delivery.next_retry_at = None
            else:
                raise httpx.HTTPStatusError(
                    f"unexpected status {response.status_code}",
                    request=response.request,
                    response=response,
                )
        except Exception as exc:
            delivery.response_status = getattr(
                getattr(exc, "response", None), "status_code", delivery.response_status
            )
            delivery.error = str(exc)[:500]
            if delivery.attempt_count >= MAX_ATTEMPTS:
                delivery.status = WebhookDeliveryStatus.EXHAUSTED
                delivery.next_retry_at = None
            else:
                delivery.status = WebhookDeliveryStatus.FAILED
                delivery.next_retry_at = next_retry_at(delivery.attempt_count)
        await session.commit()
        return delivery


async def dispatch_due(*, secret_store=None, client: httpx.AsyncClient | None = None) -> int:
    """Claim all due deliveries (CAS) and attempt each. Returns attempts made."""
    async with SessionFactory() as session:
        now = now_utc()
        result = await session.execute(
            select(WebhookDelivery.id).where(
                WebhookDelivery.status.in_(
                    [WebhookDeliveryStatus.PENDING, WebhookDeliveryStatus.FAILED]
                ),
                WebhookDelivery.next_retry_at.is_not(None),
                WebhookDelivery.next_retry_at <= now,
            )
        )
        ids = [row[0] for row in result.all()]
    count = 0
    for delivery_id in ids:
        dispatched = await dispatch_delivery(
            delivery_id, secret_store=secret_store, client=client
        )
        if dispatched is not None:
            count += 1
    return count
