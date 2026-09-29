from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.crud import InvalidQuery, apply_query, parse_query
from src.api.deps import (
    get_container,
    get_current_user,
    get_current_workspace_id,
    require_permission,
    resolve_auth_principal,
)
from src.core.dates import ensure_utc
from src.core.permissions import (
    APIKEY_CREATE,
    APIKEY_DELETE,
    APIKEY_READ,
    KEY_ONLY_PERMISSIONS,
)
from src.db.session import get_db
from src.models.api_key import ApiKey
from src.schemas.api import ApiKeyCreate, ApiKeyQuotaUpdate
from src.services.api_keys import ApiKeyError, ApiKeyForbidden, ApiKeyNotFound, ApiKeyService
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api-keys", tags=["api-keys"])

_APIKEY_FILTERABLE = {"name"}
_APIKEY_SORTABLE = {"name", "created_at", "last_used_at", "expires_at"}


def _key_dict(k: ApiKey) -> dict:
    return {
        "id": k.id,
        "workspace_id": k.workspace_id,
        "name": k.name,
        "key_prefix": k.key_prefix,
        "permissions": k.permissions,
        "created_by_user_id": k.created_by_user_id,
        "usage_count": k.usage_count,
        "usage_quota": k.usage_quota,
        "last_used_at": k.last_used_at.isoformat() if k.last_used_at else None,
        "expires_at": ensure_utc(k.expires_at).isoformat() if k.expires_at else None,
        "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
        "created_at": k.created_at.isoformat() if k.created_at else None,
    }


@router.get("")
async def list_api_keys(
    request: Request,
    response: Response,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(APIKEY_READ)),
    db: AsyncSession = Depends(get_db),
):
    # Query parsing is the HTTP layer's job; the service owns the personal
    # scope predicate, so no filter or sort can widen it.
    service = ApiKeyService(db)
    try:
        spec = parse_query(request)
        stmt = apply_query(
            service.owner_scope(workspace_id, user.id),
            ApiKey,
            spec,
            sortable=_APIKEY_SORTABLE,
            filterable=_APIKEY_FILTERABLE,
        )
        total = await service.count_for_user(workspace_id, user.id, stmt)
        rows = await service.list_for_user(
            workspace_id, user.id, stmt.offset(spec.offset).limit(spec.limit)
        )
    except InvalidQuery as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    response.headers["X-Total-Count"] = str(total)
    return [_key_dict(k) for k in rows]


@router.get("/effective-permissions")
async def effective_permissions(
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(APIKEY_READ)),
    db: AsyncSession = Depends(get_db),
):
    """Permissions this user can assign to an API key in the active workspace.

    Key-only scopes (notification:*) are always offerable: any member may hold
    them on a key (notifications are personal), mirroring ApiKeyService."""
    membership = await WorkspaceService(db).get_membership(workspace_id, user.id, active_only=True)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
    _, role = membership
    return {"permissions": sorted(set(role.permissions) | set(KEY_ONLY_PERMISSIONS))}


@router.post("", status_code=201)
async def create_api_key(
    body: ApiKeyCreate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    principal=Depends(resolve_auth_principal),
    _=Depends(require_permission(APIKEY_CREATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        key, raw = await ApiKeyService(db, container.bus).create_api_key(
            workspace_id=workspace_id,
            name=body.name,
            permissions=body.permissions,
            usage_quota=body.usage_quota,
            expires_at=body.expires_at,
            actor=user,
            ip_address=request.client.host if request.client else None,
            # When the caller is itself an API key, the new key's permissions
            # are capped by the minting key's own list as well as the owner's
            # role — a key can never grant what it does not hold.
            minting_key=principal.api_key,
        )
    except ApiKeyForbidden as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc)) from None
    except ApiKeyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return {**_key_dict(key), "key": raw}


# APIKEY_DELETE is the key-lifecycle guard: it covers quota changes and revoke.
@router.patch("/{api_key_id}")
async def set_api_key_quota(
    api_key_id: str,
    body: ApiKeyQuotaUpdate,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(APIKEY_DELETE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    # Personal scope is owned by the service (404, not 403, so another
    # user's key id is not leaked) — same as the revoke route below.
    try:
        key = await ApiKeyService(db, container.bus).set_quota(
            workspace_id,
            api_key_id,
            body.usage_quota,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except ApiKeyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ApiKeyError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    return _key_dict(key)


@router.delete("/{api_key_id}", status_code=204)
async def revoke_api_key(
    api_key_id: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(APIKEY_DELETE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    try:
        await ApiKeyService(db, container.bus).revoke_api_key(
            workspace_id,
            api_key_id,
            actor=user,
            ip_address=request.client.host if request.client else None,
        )
    except ApiKeyNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    except ApiKeyError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None
