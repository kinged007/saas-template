from __future__ import annotations

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import get_current_workspace_id, require_permission
from src.core.permissions import AUDIT_READ
from src.db.session import get_db
from src.models.audit import AuditLogEntry
from src.models.user_profile import UserProfile
from src.models.workspace import User
from src.services.audit import public_details
from src.services.profile_helpers import format_display_name

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
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
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
