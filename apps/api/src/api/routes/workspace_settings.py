from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_container, get_current_user, get_current_workspace_id, require_permission
from src.core.permissions import WORKSPACE_READ, WORKSPACE_UPDATE
from src.db.session import get_db
from src.services.workspace_settings import (
    WorkspaceSettingsNotFound,
    WorkspaceSettingsService,
    WorkspaceSettingsValidation,
)

router = APIRouter(prefix="/workspace-settings", tags=["workspace-settings"])


class WorkspaceSettingPut(BaseModel):
    value: Any


@router.get("")
async def list_workspace_settings(
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WORKSPACE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = WorkspaceSettingsService(db, container.bus, secret_store=container.secret_store)
    return await svc.list_settings(workspace_id)


@router.get("/{key}")
async def get_workspace_setting(
    key: str,
    workspace_id: str = Depends(get_current_workspace_id),
    _=Depends(require_permission(WORKSPACE_READ)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = WorkspaceSettingsService(db, container.bus, secret_store=container.secret_store)
    try:
        return await svc.get_setting(workspace_id, key)
    except WorkspaceSettingsValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except WorkspaceSettingsNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None


@router.put("/{key}")
async def put_workspace_setting(
    key: str,
    body: WorkspaceSettingPut,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WORKSPACE_UPDATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = WorkspaceSettingsService(db, container.bus, secret_store=container.secret_store)
    try:
        return await svc.upsert(
            workspace_id,
            key,
            body.value,
            actor_user_id=user.id,
            ip_address=request.client.host if request.client else None,
        )
    except WorkspaceSettingsValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


@router.delete("/{key}", status_code=204)
async def delete_workspace_setting(
    key: str,
    request: Request,
    workspace_id: str = Depends(get_current_workspace_id),
    user=Depends(get_current_user),
    _=Depends(require_permission(WORKSPACE_UPDATE)),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    svc = WorkspaceSettingsService(db, container.bus, secret_store=container.secret_store)
    try:
        await svc.delete_setting(
            workspace_id, key, actor_user_id=user.id, ip_address=request.client.host if request.client else None
        )
    except WorkspaceSettingsValidation as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    except WorkspaceSettingsNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None
    return None
