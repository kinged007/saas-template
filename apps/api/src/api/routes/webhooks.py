"""Outbound webhook subscriptions + delivery log API.

Secrets: the signing secret is returned ONCE at create/rotate and never
stored in plaintext (kept in the SecretStore).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    AuthPrincipal,
    get_container,
    get_current_workspace_id,
    require_permission,
    resolve_auth_principal,
)
from src.core.permissions import WEBHOOK_MANAGE, WEBHOOK_READ
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.events.webhook_events import webhook_event_names
from src.models.webhook import WebhookDelivery, WebhookDeliveryStatus, WebhookSubscription
from src.schemas.api import WebhookSubscriptionCreate, WebhookSubscriptionUpdate
from src.services.webhooks import WebhookService, dispatch_delivery, validate_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_SUB_SORTABLE = {"created_at", "url"}
_SUB_FILTERABLE = {"active"}
_DELIVERY_SORTABLE = {"created_at", "status", "event_type", "attempt_count"}
_DELIVERY_FILTERABLE = {"status", "event_type", "subscription_id"}


def _require_known_events(events: list[str]) -> list[str]:
    known = set(webhook_event_names())
    unknown = [e for e in events if e not in known]
    if unknown:
        raise HTTPException(422, f"unknown event types: {', '.join(unknown)}")
    return sorted(set(events))


async def _get_sub_or_404(
    subscription_id: str, workspace_id: str, db: AsyncSession
) -> WebhookSubscription:
    sub = await db.get(WebhookSubscription, subscription_id)
    if sub is None or sub.workspace_id != workspace_id:
        raise HTTPException(404, "webhook subscription not found")
    return sub


@router.get("/events")
async def list_webhook_events(
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
):
    return {"events": webhook_event_names()}


@router.get("/subscriptions")
async def list_subscriptions(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
):
    service = WebhookService(db)
    stmt = select(WebhookSubscription).where(WebhookSubscription.workspace_id == workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, WebhookSubscription, spec, sortable=_SUB_SORTABLE, filterable=_SUB_FILTERABLE
        )
    except InvalidQuery as exc:
        raise HTTPException(422, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(count.scalar_one())
    rows = await db.execute(stmt.offset(spec.offset).limit(spec.limit))
    return [service.to_dict(s) for s in rows.scalars().all()]


@router.post("/subscriptions", status_code=201)
async def create_subscription(
    body: WebhookSubscriptionCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    events = _require_known_events(body.events)
    try:
        validate_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    # create_subscription commits the row before the SecretStore put (which
    # opens its own session); the route commit below is a no-op safeguard.
    service = WebhookService(db, container.bus, container.secret_store)
    try:
        sub, secret = await service.create_subscription(
            workspace_id=workspace_id,
            url=body.url,
            events=events,
            created_by_user_id=principal.user.id,
            flush_only=True,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from None
    await db.commit()
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=sub.id,
        action="webhook.created",
        details={"url": sub.url, "events": sub.events},
        ip_address=request.client.host if request.client else None,
    )
    return {**service.to_dict(sub), "signing_secret": secret}


@router.get("/subscriptions/{subscription_id}")
async def get_subscription(
    subscription_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
):
    sub = await _get_sub_or_404(subscription_id, workspace_id, db)
    return WebhookService(db).to_dict(sub)


@router.patch("/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: str,
    body: WebhookSubscriptionUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    sub = await _get_sub_or_404(subscription_id, workspace_id, db)
    changes: dict = {}
    if body.url is not None and body.url != sub.url:
        try:
            validate_url(body.url)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        changes["url"] = {"from": sub.url, "to": body.url}
        sub.url = body.url
    if body.events is not None:
        events = _require_known_events(body.events)
        if events != list(sub.events or []):
            changes["events"] = {"from": sub.events, "to": events}
            sub.events = events
    if body.active is not None and body.active != sub.active:
        changes["active"] = {"from": sub.active, "to": body.active}
        sub.active = body.active
    if not changes:
        raise HTTPException(422, "no editable fields supplied")
    # Snapshot before publish_audit: audit-entry fan-out can also match this
    # subscription and commit delivery rows on another session, which expires
    # this session's attributes (MissingGreenlet on later lazy refresh).
    sub_id = sub.id
    snapshot = WebhookService(db).to_dict(sub)
    await db.commit()
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=sub_id,
        action="webhook.updated",
        details=changes,
        ip_address=request.client.host if request.client else None,
    )
    return snapshot


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    sub = await _get_sub_or_404(subscription_id, workspace_id, db)
    sub_url = sub.url
    await db.delete(sub)
    await db.commit()
    from src.services.webhooks import secret_key_for

    await container.secret_store.delete(
        workspace_id=workspace_id, key=secret_key_for(subscription_id)
    )
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=subscription_id,
        action="webhook.deleted",
        details={"url": sub_url},
        ip_address=request.client.host if request.client else None,
    )


@router.post("/subscriptions/{subscription_id}/rotate-secret", status_code=201)
async def rotate_secret(
    subscription_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    sub = await _get_sub_or_404(subscription_id, workspace_id, db)
    secret = await WebhookService(db, container.bus, container.secret_store).rotate_secret(sub)
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=sub.id,
        action="webhook.secret_rotated",
        details={},
        ip_address=request.client.host if request.client else None,
    )
    return {"signing_secret": secret}


@router.get("/deliveries")
async def list_deliveries(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
):
    service = WebhookService(db)
    stmt = select(WebhookDelivery).where(WebhookDelivery.workspace_id == workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt,
            WebhookDelivery,
            spec,
            sortable=_DELIVERY_SORTABLE,
            filterable=_DELIVERY_FILTERABLE,
        )
    except InvalidQuery as exc:
        raise HTTPException(422, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    response.headers["X-Total-Count"] = str(count.scalar_one())
    if not spec.sort_by:
        stmt = stmt.order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
    rows = await db.execute(stmt.offset(spec.offset).limit(spec.limit))
    return [service.delivery_to_dict(d) for d in rows.scalars().all()]


@router.get("/deliveries/{delivery_id}")
async def get_delivery(
    delivery_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
):
    delivery = await db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.workspace_id != workspace_id:
        raise HTTPException(404, "webhook delivery not found")
    out = WebhookService(db).delivery_to_dict(delivery)
    out["payload"] = delivery.payload
    return out


@router.post("/deliveries/{delivery_id}/redeliver", status_code=201)
async def redeliver(
    delivery_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    from src.core.dates import now_utc

    delivery = await db.get(WebhookDelivery, delivery_id)
    if delivery is None or delivery.workspace_id != workspace_id:
        raise HTTPException(404, "webhook delivery not found")
    if delivery.status not in (
        WebhookDeliveryStatus.FAILED,
        WebhookDeliveryStatus.EXHAUSTED,
        WebhookDeliveryStatus.SUCCESS,
    ):
        raise HTTPException(409, "only finished deliveries can be redelivered")
    delivery.status = WebhookDeliveryStatus.PENDING
    delivery.attempt_count = 0
    delivery.next_retry_at = now_utc()
    delivery.error = None
    delivery.response_status = None
    await db.commit()
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=delivery.id,
        action="webhook.redelivered",
        details={"subscription_id": delivery.subscription_id},
        ip_address=request.client.host if request.client else None,
    )
    await dispatch_delivery(
        delivery.id, secret_store=container.secret_store
    )
    await db.refresh(delivery)
    # Re-read in this session (dispatch ran in its own session).
    updated = await db.get(WebhookDelivery, delivery_id)
    return WebhookService(db).delivery_to_dict(updated)
