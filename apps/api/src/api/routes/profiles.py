from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    AuthPrincipal,
    get_container,
    get_current_user,
    require_superuser,
    resolve_auth_principal,
)
from src.db.session import get_db
from src.models.workspace import User
from src.schemas.api import DeleteMeRequest, ProfileUpdate
from src.services.profiles import ProfileService
from src.services.serializers import profile_to_dict

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profiles"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("/me/profile")
async def get_my_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    profile = await service.get_or_create(user.id)
    return profile_to_dict(profile)


@router.put("/me/profile")
async def put_my_profile(
    body: ProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    # Use exclude_unset to know which fields were provided
    data = body.model_dump(exclude_unset=True, mode="python")
    # Convert AnyHttpUrl to str if needed
    if "website_url" in data and data["website_url"] is not None:
        data["website_url"] = str(data["website_url"])
    if "avatar_url" in data and data["avatar_url"] is not None:
        data["avatar_url"] = str(data["avatar_url"])
    profile = await service.update(
        user.id, data, is_put=True, ip_address=_client_ip(request), actor_user_id=user.id
    )
    return profile_to_dict(profile)


@router.patch("/me/profile")
async def patch_my_profile(
    body: ProfileUpdate,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    data = body.model_dump(exclude_unset=True, mode="python")
    if "website_url" in data and data["website_url"] is not None:
        data["website_url"] = str(data["website_url"])
    if "avatar_url" in data and data["avatar_url"] is not None:
        data["avatar_url"] = str(data["avatar_url"])
    profile = await service.update(
        user.id, data, is_put=False, ip_address=_client_ip(request), actor_user_id=user.id
    )
    return profile_to_dict(profile)


@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    proj = await service.get_public_projection(
        user_id, viewer=principal.user, is_deployment_admin=principal.is_deployment_admin
    )
    if proj is None:
        raise HTTPException(status_code=404, detail="user or profile not found")
    return proj


@router.get("/me/export")
async def export_my_data(
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    bundle = await service.export_bundle(user.id)
    # Return JSON with attachment disposition
    # Use Response to set headers
    import json

    body = json.dumps(bundle)
    safe_ts = bundle["exported_at"].replace(":", "-").replace('"', "")
    headers = {"Content-Disposition": f'attachment; filename="export-{user.id}-{safe_ts}.json"'}
    return Response(content=body, media_type="application/json", headers=headers)


@router.get("/users/{user_id}/export")
async def export_user_data(
    user_id: str,
    _: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    bundle = await service.export_bundle(user_id)
    import json

    body = json.dumps(bundle)
    safe_ts = bundle["exported_at"].replace(":", "-").replace('"', "")
    headers = {"Content-Disposition": f'attachment; filename="export-{user_id}-{safe_ts}.json"'}
    return Response(content=body, media_type="application/json", headers=headers)


@router.delete("/me", status_code=204)
async def delete_me(
    body: DeleteMeRequest,
    request: Request,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    await service.delete_account(
        user.id,
        confirm=body.confirm,
        password=body.password,
        ip_address=_client_ip(request),
        actor_user_id=user.id,
    )
    return None


@router.delete("/users/{user_id}", status_code=204)
async def delete_user(
    user_id: str,
    request: Request,
    actor: User = Depends(require_superuser),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    service = ProfileService(db, container.bus)
    await service.delete_account_superuser(user_id, actor=actor, ip_address=_client_ip(request))
    return None
