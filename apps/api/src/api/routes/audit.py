from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_permission,
)
from src.core.dates import ensure_utc, iso_or_none, now_utc
from src.core.permissions import AUDIT_READ
from src.core.security.ratelimit import get_export_limiter
from src.db.session import get_db
from src.events.publisher import publish_audit
from src.models.audit import AuditLogEntry
from src.models.user_profile import UserProfile
from src.models.workspace import User
from src.services.audit import public_details
from src.services.profile_helpers import format_display_name
from src.services.search_export import SearchExportService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/audit", tags=["audit"])

_AUDIT_SORTABLE = {"created_at", "action", "resource_type"}
_AUDIT_FILTERABLE = {"action", "resource_type", "actor_user_id"}


def _audit_to_dict(
    entry: AuditLogEntry, actor: User | None = None, profile: UserProfile | None = None
) -> dict:
    actor_name = None
    if actor is not None:
        if profile is not None and (profile.first_name or profile.last_name):
            actor_name = format_display_name(
                profile.first_name, profile.last_name, actor.display_name
            )
        else:
            actor_name = actor.display_name
    return {
        "id": entry.id,
        "workspace_id": entry.workspace_id,
        "actor_user_id": entry.actor_user_id,
        "actor_display_name": actor_name,
        "actor_email": actor.email if actor is not None else None,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "action": entry.action,
        "details": public_details(entry.details),
        "ip_address": entry.ip_address,
        "created_at": iso_or_none(entry.created_at),
    }


@router.get("")
async def list_audit_logs(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(AuditLogEntry, User, UserProfile)
        .outerjoin(User, User.id == AuditLogEntry.actor_user_id)
        .outerjoin(UserProfile, UserProfile.user_id == User.id)
        .where(AuditLogEntry.workspace_id == workspace_id)
    )
    try:
        spec = parse_query(request)
        stmt = apply_query(
            stmt, AuditLogEntry, spec, sortable=_AUDIT_SORTABLE, filterable=_AUDIT_FILTERABLE
        )
        q = (request.query_params.get("q") or "").strip()
        if q:
            # Cross-field search scoped to this workspace: substring match on
            # user name/email or action, plus exact match on id columns
            # (guarded: non-UUID terms must not reach UUID comparisons).
            like = f"%{q}%"
            clauses = [
                AuditLogEntry.action.ilike(like),
                User.display_name.ilike(like),
                User.email.ilike(like),
            ]
            try:
                uuid.UUID(q)
            except ValueError:
                pass
            else:
                clauses.extend(
                    (
                        AuditLogEntry.id == q,
                        AuditLogEntry.actor_user_id == q,
                        AuditLogEntry.resource_id == q,
                    )
                )
            stmt = stmt.where(or_(*clauses))
    except InvalidQuery as exc:
        raise HTTPException(422, str(exc)) from None

    count = await db.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
    total = count.scalar_one()

    if not spec.sort_by:
        stmt = stmt.order_by(AuditLogEntry.created_at.desc(), AuditLogEntry.id.desc())
    stmt = stmt.offset(spec.offset).limit(spec.limit)
    rows = await db.execute(stmt)
    response.headers["X-Total-Count"] = str(total)
    return [_audit_to_dict(entry, user, profile) for entry, user, profile in rows.all()]


@router.get("/export")
async def export_audit_logs(
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(AUDIT_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
    format: str = "json",
    action: str | None = None,
    resource_type: str | None = None,
    actor_user_id: str | None = None,
    q: str | None = None,
    from_: datetime | None = Query(default=None, alias="from"),
    to: datetime | None = Query(default=None, alias="to"),
):
    """Downloadable audit dump: the workspace export's audit section without
    the bundle, filterable like the list (action, resource type, actor,
    free-text search, created-at range). Capped at the export cap;
    `truncated` flags a cut, so a compliance pull can page on created_at
    instead of assuming completeness. Throttled per workspace."""
    if format not in ("json", "csv"):
        raise HTTPException(422, f"unknown format: {format} (choose from csv, json)")
    if from_ is not None and to is not None and ensure_utc(to) < ensure_utc(from_):
        raise HTTPException(422, "to must not be earlier than from")
    limiter = get_export_limiter()
    export_key = f"audit-export:{workspace_id}"
    limiter.check(export_key)
    limiter.fail(export_key)
    from src.services.conversations import ConversationForbidden

    service = SearchExportService(db, container.bus)
    try:
        rows, truncated = await service.export_audit(
            workspace_id=workspace_id,
            user_id=user.id,
            action=action or None,
            resource_type=resource_type or None,
            actor_user_id=actor_user_id or None,
            q=q or None,
            created_from=from_,
            created_to=to,
        )
    except ConversationForbidden as exc:
        raise HTTPException(403, str(exc)) from None
    await publish_audit(
        container.bus,
        workspace_id=workspace_id,
        resource_type="audit",
        resource_id=workspace_id,
        action="audit.exported",
        actor_user_id=user.id,
        details={
            "format": format,
            "count": len(rows),
            "truncated": truncated,
            "action": action,
            "resource_type": resource_type,
            "actor_user_id": actor_user_id,
            "q": q,
            "from": iso_or_none(from_) if from_ else None,
            "to": iso_or_none(to) if to else None,
        },
    )
    if format == "csv":
        return Response(
            content=SearchExportService.export_csv({"audit": rows}, "audit"),
            media_type="text/csv",
            headers={
                "Content-Disposition": f'attachment; filename="audit-{workspace_id}.csv"',
                "X-Truncated": str(truncated).lower(),
            },
        )
    return Response(
        content=json.dumps(
            {"exported_at": now_utc().isoformat(), "truncated": truncated, "audit": rows}
        ),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="audit-{workspace_id}.json"',
            "X-Truncated": str(truncated).lower(),
        },
    )
