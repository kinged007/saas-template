"""Outbound webhook signing, dispatch, and retry.

Signature scheme (documented for subscribers, see docs/WEBHOOKS.md):
  `X-Webhook-Signature: sha256=<hmac_sha256_hex(secret, timestamp + "." + raw_body)>`
plus `X-Webhook-Event` (public event name), `X-Webhook-Delivery` (delivery
id, for dedupe), and `X-Webhook-Timestamp`. Success is any 2xx; anything else
retries with backoff until `MAX_ATTEMPTS`, then the delivery is `exhausted`.

Delivery is at-least-once and unordered across retries — subscribers must
dedupe on `X-Webhook-Delivery` / `event_id`.
"""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import urllib.parse
from datetime import timedelta

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.events.bus import EventBus
from src.events.webhook_events import webhook_event_for_subject, webhook_event_names
from src.models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription
from src.secrets.base import SecretStore

logger = logging.getLogger(__name__)

SIGNATURE_HEADER = "X-Webhook-Signature"
EVENT_HEADER = "X-Webhook-Event"
DELIVERY_HEADER = "X-Webhook-Delivery"
TIMESTAMP_HEADER = "X-Webhook-Timestamp"

DELIVERY_TIMEOUT_SECONDS = 10.0
MAX_ATTEMPTS = 6
# Backoff after attempt N (1-based): 1m, 5m, 30m, 2h, 12h. Attempt 6 is the
# last; failing it exhausts the delivery instead of scheduling a retry.
BACKOFF_SECONDS = [60, 300, 1800, 7200, 43200]

MAX_URL_LENGTH = 2000
MAX_PAYLOAD_BYTES = 256 * 1024
MAX_ERROR_LENGTH = 2000

SECRET_KIND = "webhook_signing_secret"

def secret_key_for(subscription_id: str) -> str:
    return f"webhooks:{subscription_id}:signing_secret"

def generate_secret() -> str:
    return secrets.token_urlsafe(32)

def sign_payload(secret: str, timestamp: str, raw_body: bytes) -> str:
    """`sha256=<hex>` HMAC over `timestamp + "." + raw_body`."""
    mac = hmac.new(secret.encode(), timestamp.encode() + b"." + raw_body, hashlib.sha256)
    return f"sha256={mac.hexdigest()}"

def verify_signature(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    expected = sign_payload(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, signature)

def next_retry_delay(attempt: int) -> int | None:
    """Backoff seconds after `attempt` (1-based), or None when exhausted."""
    if attempt >= MAX_ATTEMPTS:
        return None
    return BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)]

def validate_url(url: str, *, allow_private: bool = False) -> str:
    """SSRF guard: https-only in prod, no loopback/private targets by default."""
    from src.settings import settings

    if len(url) > MAX_URL_LENGTH:
        raise WebhookError(f"url exceeds {MAX_URL_LENGTH} characters")
    try:
        parsed = urllib.parse.urlparse(url)
    except ValueError as exc:
        raise WebhookError(f"invalid url: {exc}") from None
    if parsed.scheme not in ("http", "https"):
        raise WebhookError("url must use http or https")
    if settings.environment == "production" and parsed.scheme != "https":
        raise WebhookError("url must use https in production")
    host = parsed.hostname or ""
    if not host:
        raise WebhookError("url must include a host")
    if not allow_private:
        try:
            addr = ipaddress.ip_address(host)
            blocked = addr.is_private or addr.is_loopback
        except ValueError:
            lowered = host.lower()
            blocked = lowered in ("localhost",) or lowered.endswith((".local", ".internal"))
        if blocked:
            raise WebhookError("url targets a private or loopback address")
    return url

def validate_events(events: list[str]) -> list[str]:
    known = set(webhook_event_names())
    unknown = [e for e in events if e not in known]
    if unknown:
        raise WebhookError(f"unknown event types: {', '.join(unknown)}")
    return sorted(set(events))

class WebhookError(Exception):
    pass

def subscription_to_dict(s: WebhookSubscription) -> dict:
    return {
        "id": s.id,
        "workspace_id": s.workspace_id,
        "url": s.url,
        "events": s.events or [],
        "active": s.active,
        "created_by_user_id": s.created_by_user_id,
        "created_at": s.created_at.isoformat() if s.created_at else None,
        "updated_at": s.updated_at.isoformat() if s.updated_at else None,
    }

def delivery_to_dict(d: WebhookDelivery) -> dict:
    return {
        "id": d.id,
        "subscription_id": d.subscription_id,
        "workspace_id": d.workspace_id,
        "event_type": d.event_type,
        "subject": d.subject,
        "payload": d.payload or {},
        "status": d.status,
        "attempt_count": d.attempt_count,
        "next_retry_at": d.next_retry_at.isoformat() if d.next_retry_at else None,
        "last_attempt_at": d.last_attempt_at.isoformat() if d.last_attempt_at else None,
        "response_status": d.response_status,
        "error": d.error,
        "event_id": d.event_id,
        "correlation_id": d.correlation_id,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }

class WebhookService:
    """Route-facing CRUD on the request-scoped session."""

    def __init__(self, session: AsyncSession, secret_store: SecretStore | None = None) -> None:
        self._session = session
        self._secrets = secret_store

    async def _get_or_404(self, workspace_id: str, subscription_id: str) -> WebhookSubscription:
        sub = await self._session.get(WebhookSubscription, subscription_id)
        if sub is None or sub.workspace_id != workspace_id:
            raise WebhookError("webhook subscription not found")
        return sub

    async def list_subscriptions(self, workspace_id: str) -> list[WebhookSubscription]:
        rows = await self._session.execute(
            select(WebhookSubscription)
            .where(WebhookSubscription.workspace_id == workspace_id)
            .order_by(WebhookSubscription.created_at.asc())
        )
        return list(rows.scalars().all())

    async def create_subscription(
        self,
        workspace_id: str,
        *,
        url: str,
        events: list[str],
        active: bool = True,
        created_by_user_id: str | None = None,
    ) -> tuple[WebhookSubscription, str]:
        validate_url(url)
        clean_events = validate_events(events)
        sub = WebhookSubscription(
            workspace_id=workspace_id,
            url=url,
            events=clean_events,
            active=active,
            created_by_user_id=created_by_user_id,
        )
        self._session.add(sub)
        await self._session.commit()
        await self._session.refresh(sub)
        secret = generate_secret()
        if self._secrets is not None:
            await self._secrets.put(
                workspace_id=workspace_id,
                key=secret_key_for(sub.id),
                value=secret,
                kind=SECRET_KIND,
                label=f"webhook signing secret for {url}",
            )
        return sub, secret

    async def update_subscription(
        self,
        workspace_id: str,
        subscription_id: str,
        *,
        url: str | None = None,
        events: list[str] | None = None,
        active: bool | None = None,
    ) -> WebhookSubscription:
        sub = await self._get_or_404(workspace_id, subscription_id)
        if url is not None:
            sub.url = validate_url(url)
        if events is not None:
            sub.events = validate_events(events)
        if active is not None:
            sub.active = active
        await self._session.commit()
        await self._session.refresh(sub)
        return sub

    async def delete_subscription(self, workspace_id: str, subscription_id: str) -> None:
        sub = await self._get_or_404(workspace_id, subscription_id)
        await self._session.delete(sub)
        await self._session.commit()
        if self._secrets is not None:
            await self._secrets.delete(
                workspace_id=workspace_id, key=secret_key_for(subscription_id)
            )

    async def rotate_secret(self, workspace_id: str, subscription_id: str) -> str:
        await self._get_or_404(workspace_id, subscription_id)
        secret = generate_secret()
        if self._secrets is not None:
            await self._secrets.put(
                workspace_id=workspace_id,
                key=secret_key_for(subscription_id),
                value=secret,
                kind=SECRET_KIND,
            )
        return secret

    async def list_deliveries(
        self, workspace_id: str, *, subscription_id: str | None = None
    ):
        stmt = select(WebhookDelivery).where(WebhookDelivery.workspace_id == workspace_id)
        if subscription_id is not None:
            await self._get_or_404(workspace_id, subscription_id)
            stmt = stmt.where(WebhookDelivery.subscription_id == subscription_id)
        return stmt

    async def get_delivery(self, workspace_id: str, delivery_id: str) -> WebhookDelivery:
        delivery = await self._session.get(WebhookDelivery, delivery_id)
        if delivery is None or delivery.workspace_id != workspace_id:
            raise WebhookError("webhook delivery not found")
        return delivery

    async def redeliver(self, workspace_id: str, delivery_id: str) -> WebhookDelivery:
        delivery = await self.get_delivery(workspace_id, delivery_id)
        delivery.status = WebhookDeliveryStatus.PENDING
        delivery.next_retry_at = now_utc()
        delivery.error = None
        delivery.response_status = None
        await self._session.commit()
        await self._session.refresh(delivery)
        return delivery

# ------------------------------------------------------------ fan-out + retry
# Background paths own short-lived sessions (same discipline as workflows and
# the job scheduler): fan-out inserts one pending row per matching
# subscription, then dispatch claims due rows with a CAS update so exactly one
# replica delivers each attempt.

def build_envelope(
    *,
    event_type: str,
    event_id: str,
    occurred_at: str,
    workspace_id: str | None,
    data: dict,
) -> dict:
    return {
        "event": event_type,
        "event_id": event_id,
        "occurred_at": occurred_at,
        "workspace_id": workspace_id,
        "data": data,
    }

async def fan_out_event(
    session: AsyncSession,
    *,
    subject: str,
    payload: dict,
    event_id: str,
    correlation_id: str | None,
    occurred_at: str,
) -> int:
    """Insert one pending delivery per active subscription matching `subject`.

    Returns the number of deliveries enqueued. Events without a workspace_id
    (user-scoped auth events, ...) are skipped — subscriptions are
    workspace-scoped.
    """
    event_type = webhook_event_for_subject(subject)
    if event_type is None:
        return 0
    workspace_id = payload.get("workspace_id")
    if not workspace_id:
        return 0
    rows = (
        await session.execute(
            select(WebhookSubscription).where(
                WebhookSubscription.workspace_id == workspace_id,
                WebhookSubscription.active.is_(True),
            )
        )
    ).scalars().all()
    count = 0
    for sub in rows:
        if sub.events and event_type not in (sub.events or []):
            continue
        session.add(
            WebhookDelivery(
                subscription_id=sub.id,
                workspace_id=workspace_id,
                event_type=event_type,
                subject=subject,
                payload=build_envelope(
                    event_type=event_type,
                    event_id=event_id,
                    occurred_at=occurred_at,
                    workspace_id=workspace_id,
                    data=payload,
                ),
                status=WebhookDeliveryStatus.PENDING,
                next_retry_at=now_utc(),
                event_id=event_id,
                correlation_id=correlation_id,
            )
        )
        count += 1
    if count:
        await session.commit()
    return count

async def _fetch_secret(
    secret_store: SecretStore | None, workspace_id: str, sub_id: str
) -> str | None:
    if secret_store is None:
        return None
    record = await secret_store.get(workspace_id=workspace_id, key=secret_key_for(sub_id))
    return record.value if record else None

async def deliver_once(
    delivery: WebhookDelivery,
    url: str,
    secret: str | None,
    *,
    client: httpx.AsyncClient | None = None,
) -> tuple[bool, int | None, str | None]:
    """POST one delivery. Returns (ok, response_status, error_excerpt)."""
    raw_body = json.dumps(delivery.payload or {}, separators=(",", ":")).encode()
    if len(raw_body) > MAX_PAYLOAD_BYTES:
        return False, None, f"payload exceeds {MAX_PAYLOAD_BYTES} bytes"
    timestamp = now_utc().isoformat()
    headers = {
        EVENT_HEADER: delivery.event_type,
        DELIVERY_HEADER: delivery.id,
        TIMESTAMP_HEADER: timestamp,
        "Content-Type": "application/json",
    }
    if secret:
        headers[SIGNATURE_HEADER] = sign_payload(secret, timestamp, raw_body)
    try:
        if client is None:
            async with httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_SECONDS) as owned:
                response = await owned.post(url, content=raw_body, headers=headers)
        else:
            response = await client.post(
                url, content=raw_body, headers=headers, timeout=DELIVERY_TIMEOUT_SECONDS
            )
    except Exception as exc:
        return False, None, str(exc)[:MAX_ERROR_LENGTH]
    if 200 <= response.status_code < 300:
        return True, response.status_code, None
    body = (response.text or "")[:MAX_ERROR_LENGTH]
    return False, response.status_code, f"unexpected status {response.status_code}: {body}"

async def dispatch_due(
    session: AsyncSession,
    secret_store: SecretStore | None = None,
    *,
    bus: EventBus | None = None,
    client: httpx.AsyncClient | None = None,
    limit: int = 50,
) -> int:
    """One dispatch pass: CAS-claim due deliveries and POST them.

    Returns the number of deliveries attempted. Each claim is a conditional
    update on (id, status, next_retry_at) so exactly one replica attempts a
    delivery; the attempt outcome (success / retry / exhausted) is written in
    the same session before moving on.
    """
    now = now_utc()
    stmt = (
        select(WebhookDelivery)
        .where(
            WebhookDelivery.status == WebhookDeliveryStatus.PENDING,
            WebhookDelivery.next_retry_at.is_not(None),
        )
        .order_by(WebhookDelivery.next_retry_at.asc())
        .limit(limit)
    )
    rows = (await session.execute(stmt)).scalars().all()
    due = [
        d
        for d in rows
        if d.next_retry_at is None or ensure_utc(d.next_retry_at) <= now
    ]
    attempted = 0
    for delivery in due:
        claimed_at = delivery.next_retry_at
        result = await session.execute(
            update(WebhookDelivery)
            .where(
                WebhookDelivery.id == delivery.id,
                WebhookDelivery.status == WebhookDeliveryStatus.PENDING,
                WebhookDelivery.next_retry_at == claimed_at,
            )
            .values(next_retry_at=None)
        )
        if result.rowcount != 1:
            await session.rollback()
            continue  # another replica claimed this delivery
        await session.commit()
        await session.refresh(delivery)

        sub = await session.get(WebhookSubscription, delivery.subscription_id)
        if sub is None or not sub.active:
            delivery.status = WebhookDeliveryStatus.EXHAUSTED
            delivery.error = "subscription deleted or deactivated"
            delivery.next_retry_at = None
            await session.commit()
            continue

        secret = await _fetch_secret(secret_store, delivery.workspace_id, sub.id)
        ok, response_status, error = await deliver_once(delivery, sub.url, secret, client=client)
        delivery.attempt_count += 1
        delivery.last_attempt_at = now_utc()
        delivery.response_status = response_status
        if ok:
            delivery.status = WebhookDeliveryStatus.SUCCESS
            delivery.error = None
            delivery.next_retry_at = None
        else:
            delay = next_retry_delay(delivery.attempt_count)
            delivery.error = error
            if delay is None:
                delivery.status = WebhookDeliveryStatus.EXHAUSTED
                delivery.next_retry_at = None
            else:
                delivery.next_retry_at = now_utc() + timedelta(seconds=delay)
        await session.commit()
        attempted += 1
        logger.info(
            "webhook delivery %s attempt %d -> %s",
            delivery.id, delivery.attempt_count, delivery.status,
        )
    return attempted
