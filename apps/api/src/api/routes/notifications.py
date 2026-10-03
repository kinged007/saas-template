from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, QuerySpec, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    get_optional_workspace_id,
    require_key_permission,
    resolve_auth_principal,
)
from src.core.permissions import NOTIFICATION_READ, NOTIFICATION_UPDATE
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.models.core import Notification
from src.models.workspace import Workspace
from src.schemas.api import NotificationAck, NotificationPreferencesUpdate
from src.services.notifications import (
    CHANNELS,
    DIGEST_TYPE,
    NotificationService,
)
from src.services.serializers import notification_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/notifications", tags=["notifications"])

_NOTIFICATION_FILTERABLE = {"type", "acknowledged_at", "acknowledged", "workspace_id"}
_NOTIFICATION_SORTABLE = {"created_at", "type", "acknowledged_at"}
# Newest first, id breaking created_at ties — see _MEMBER_DEFAULT_ORDER.
_NOTIFICATION_DEFAULT_ORDER = (Notification.created_at.desc(), Notification.id.desc())


def _row_dict(n: Notification, workspace_name: str | None = None) -> dict:
    data = notification_to_dict(n, workspace_name=workspace_name)
    data["acknowledged"] = data["acknowledged_at"] is not None
    return data


def _apply_notification_spec(stmt, spec: QuerySpec) -> Select:
    """Rewrite the convenience `acknowledged` filter (read/unread) onto the
    nullable `acknowledged_at` column before applying the whitelisted query."""
    rewritten = []
    for field, op, value in spec.filters:
        if field == "acknowledged":
            is_read = str(value).strip().lower() in ("true", "1")
            rewritten.append(("acknowledged_at", "isnotnull" if is_read else "isnull", ""))
        else:
            rewritten.append((field, op, value))
    spec.filters = rewritten
    return apply_query(
        stmt,
        Notification,
        spec,
        sortable=_NOTIFICATION_SORTABLE,
        filterable=_NOTIFICATION_FILTERABLE,
    )


@router.get("")
async def list_notifications(
    request: Request,
    response: Response,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_READ)),
    workspace_id: str = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Notification, Workspace.name)
        .outerjoin(Workspace, Workspace.id == Notification.workspace_id)
        .where(Notification.user_id == user.id, Notification.workspace_id == workspace_id)
    )
    try:
        spec = parse_query(request)
        stmt = _apply_notification_spec(stmt, spec)
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()
    if not spec.sort_by:
        stmt = stmt.order_by(*_NOTIFICATION_DEFAULT_ORDER)
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_row_dict(n, workspace_name=name) for n, name in rows.all()]


@router.get("/unread-count")
async def unread_count(
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_READ)),
    workspace_id: str = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
):
    count = await NotificationService(db).unread_count(user.id, workspace_id=workspace_id)
    return {"count": count}


@router.get("/preferences")
async def get_preferences(
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_READ)),
    db: AsyncSession = Depends(get_db),
):
    prefs = await NotificationService(db).get_preferences(user.id)
    digest = next((p.digest_enabled for p in prefs if p.type == DIGEST_TYPE), False)
    return {
        "channels": {p.type: p.channel for p in prefs if p.type != DIGEST_TYPE},
        "digest_enabled": digest,
    }


@router.put("/preferences")
async def update_preferences(
    body: NotificationPreferencesUpdate,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_UPDATE)),
    db: AsyncSession = Depends(get_db),
):
    for type, channel in body.channels.items():
        if len(type) > 50:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"unknown type {type!r}")
        if channel not in CHANNELS:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, f"invalid channel {channel!r}"
            )
    service = NotificationService(db)
    if body.channels:
        await service.upsert_channels(user.id, body.channels)
    if body.digest_enabled is not None:
        await service.set_digest(user.id, body.digest_enabled)
    prefs = await service.get_preferences(user.id)
    digest = next((p.digest_enabled for p in prefs if p.type == DIGEST_TYPE), False)
    return {
        "channels": {p.type: p.channel for p in prefs if p.type != DIGEST_TYPE},
        "digest_enabled": digest,
    }


@router.get("/unsubscribe", response_class=PlainTextResponse)
async def unsubscribe(
    token: str = Query(min_length=1, max_length=128),
    type: str = Query(default="all", max_length=50),
    db: AsyncSession = Depends(get_db),
):
    """One-click email opt-out (no auth): the token proves mailbox ownership."""
    if not await NotificationService(db).unsubscribe(token, type):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "invalid unsubscribe link")
    return "You have been unsubscribed from these emails. In-app notifications are unaffected."


@router.patch("/read-all")
async def acknowledge_all(
    request: Request,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_UPDATE)),
    workspace_id: str = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = NotificationService(db, container.bus)
    ip = request.client.host if request.client else None
    count = await service.acknowledge_all(user.id, workspace_id=workspace_id, ip_address=ip)
    return {"acknowledged": count}


@router.patch("/{notification_id}")
async def acknowledge(
    notification_id: str,
    body: NotificationAck,
    request: Request,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_UPDATE)),
    workspace_id: str | None = Depends(get_optional_workspace_id),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = NotificationService(db, container.bus)
    ip = request.client.host if request.client else None
    ws = workspace_id  # already optional; when provided, enforce workspace scoping
    if body.acknowledged:
        n = await service.acknowledge(user.id, notification_id, workspace_id=ws, ip_address=ip)
    else:
        n = await service.unacknowledge(user.id, notification_id, workspace_id=ws, ip_address=ip)
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    name = (
        await db.execute(select(Workspace.name).where(Workspace.id == n.workspace_id))
    ).scalar_one_or_none()
    return _row_dict(n, workspace_name=name)


@router.delete("/{notification_id}", status_code=204)
async def delete_notification(
    notification_id: str,
    request: Request,
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_key_permission(NOTIFICATION_UPDATE)),
    workspace_id: str | None = Depends(get_optional_workspace_id),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    stmt = select(Notification).where(
        Notification.id == notification_id, Notification.user_id == user.id
    )
    if workspace_id is not None:
        stmt = stmt.where(Notification.workspace_id == workspace_id)
    n = (await db.execute(stmt)).scalar_one_or_none()
    if n is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "notification not found")
    await db.delete(n)
    await db.commit()
    await publish_audit(
        container.bus,
        workspace_id=n.workspace_id,
        resource_type="notification",
        resource_id=n.id,
        action="notification.deleted",
        actor_user_id=user.id,
        ip_address=request.client.host if request.client else None,
    )
