"""Outbound webhook subscriptions + delivery log.

Workspace-scoped: subscriptions and deliveries are always read through the
request's workspace id, and cross-workspace ids 404 (never 403) so callers
cannot probe other workspaces' existence.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_permission,
)
from src.core.permissions import WEBHOOK_MANAGE, WEBHOOK_READ
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.events.webhook_events import webhook_event_names
from src.models.webhook import WebhookDelivery
from src.schemas.api import WebhookSubscriptionCreate, WebhookSubscriptionUpdate
from src.services.webhooks import (
    WebhookError,
    WebhookService,
    delivery_to_dict,
    dispatch_due,
    subscription_to_dict,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_SUB_SORTABLE = {"created_at", "url"}
_SUB_FILTERABLE = {"active", "url"}
_DELIVERY_SORTABLE = {"created_at", "status", "attempt_count"}
_DELIVERY_FILTERABLE = {"status", "event_type", "subscription_id"}


@router.get("/events")
async def list_webhook_events(
    _=Depends(require_permission(WEBHOOK_READ)),
):
    """Public event names subscribers can filter on."""
    return {"events": webhook_event_names()}


@router.get("/subscriptions")
async def list_subscriptions(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
):
    from src.models.webhook import WebhookSubscription

    stmt = select(WebhookSubscription).where(WebhookSubscription.workspace_id == workspace_id)
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, WebhookSubscription, spec, sortable=_SUB_SORTABLE, filterable=_SUB_FILTERABLE
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [subscription_to_dict(s) for s in rows.scalars().all()]


@router.post("/subscriptions", status_code=201)
async def create_subscription(
    body: WebhookSubscriptionCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        sub, secret = await WebhookService(db, container.secret_store).create_subscription(
            workspace_id,
            url=str(body.url),
            events=body.events,
            active=body.active,
            created_by_user_id=user.id,
        )
    except WebhookError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=sub.id,
        action="webhook.created",
        actor_user_id=user.id,
        details={"url": sub.url, "events": sub.events},
        ip_address=request.client.host if request.client else None,
    )
    return {**subscription_to_dict(sub), "secret": secret}


@router.patch("/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: str,
    body: WebhookSubscriptionUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    if body.url is None and body.events is None and body.active is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "no editable fields supplied")
    try:
        sub = await WebhookService(db, container.secret_store).update_subscription(
            workspace_id,
            subscription_id,
            url=str(body.url) if body.url is not None else None,
            events=body.events,
            active=body.active,
        )
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=sub.id,
        action="webhook.updated",
        actor_user_id=user.id,
        details={"url": sub.url, "events": sub.events, "active": sub.active},
        ip_address=request.client.host if request.client else None,
    )
    return subscription_to_dict(sub)


@router.delete("/subscriptions/{subscription_id}", status_code=204)
async def delete_subscription(
    subscription_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        await WebhookService(db, container.secret_store).delete_subscription(
            workspace_id, subscription_id
        )
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=subscription_id,
        action="webhook.deleted",
        actor_user_id=user.id,
        details={},
        ip_address=request.client.host if request.client else None,
    )


@router.post("/subscriptions/{subscription_id}/rotate-secret", status_code=201)
async def rotate_secret(
    subscription_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        secret = await WebhookService(db, container.secret_store).rotate_secret(
            workspace_id, subscription_id
        )
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=subscription_id,
        action="webhook.secret_rotated",
        actor_user_id=user.id,
        details={},
        ip_address=request.client.host if request.client else None,
    )
    return {"secret": secret}


@router.get("/deliveries")
async def list_deliveries(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        stmt = await WebhookService(db, container.secret_store).list_deliveries(workspace_id)
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    # Default: newest first.
    if not spec.sort_by:
        stmt = stmt.order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [delivery_to_dict(d) for d in rows.scalars().all()]


@router.get("/subscriptions/{subscription_id}/deliveries")
async def list_subscription_deliveries(
    subscription_id: str,
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        stmt = await WebhookService(db, container.secret_store).list_deliveries(
            workspace_id, subscription_id=subscription_id
        )
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
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
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    if not spec.sort_by:
        stmt = stmt.order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [delivery_to_dict(d) for d in rows.scalars().all()]


@router.get("/deliveries/{delivery_id}")
async def get_delivery(
    delivery_id: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WEBHOOK_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        delivery = await WebhookService(db, container.secret_store).get_delivery(
            workspace_id, delivery_id
        )
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return delivery_to_dict(delivery)


@router.post("/deliveries/{delivery_id}/redeliver")
async def redeliver(
    delivery_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WEBHOOK_MANAGE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        service = WebhookService(db, container.secret_store)
        delivery = await service.redeliver(workspace_id, delivery_id)
    except WebhookError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="webhook",
        resource_id=delivery.id,
        action="webhook.redelivered",
        actor_user_id=user.id,
        details={"subscription_id": delivery.subscription_id, "event_type": delivery.event_type},
        ip_address=request.client.host if request.client else None,
    )
    # Best-effort immediate attempt so the caller sees progress without
    # waiting for the next dispatch tick; failures stay pending for retry.
    try:
        await dispatch_due(db, container.secret_store, limit=1)
        await db.refresh(delivery)
    except Exception:
        logger.exception("immediate redelivery attempt failed for %s", delivery_id)
    return delivery_to_dict(delivery)
