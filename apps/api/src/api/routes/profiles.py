from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import (
    AuthPrincipal,
    can_target_profile_update,
    get_container,
    get_current_user,
    get_current_workspace_id,
    get_optional_workspace_id,
    require_superuser,
    require_target_profile_update,
    resolve_auth_principal,
)
from src.core.dates import ensure_utc, now_utc
from src.db.session import get_db
from src.models.workspace import User
from src.schemas.api import (
    DeleteMeRequest,
    MemberPasswordUpdate,
    NotificationPreferencesUpdate,
    ProfileUpdate,
    SessionRead,
)
from src.services.auth import AuthError, AuthService
from src.services.notifications import CHANNELS, DIGEST_TYPE, NotificationService
from src.services.profiles import ProfileService
from src.services.serializers import profile_to_dict, session_to_dict
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["profiles"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None

def _profile_payload(body: ProfileUpdate) -> dict:
    """Validated fields, with AnyHttpUrl values flattened to str for the column."""
    data = body.model_dump(exclude_unset=True, mode="python")
    for field in ("website_url", "avatar_url"):
        if data.get(field) is not None:
            data[field] = str(data[field])
    return data


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
    profile = await service.update(
        user.id, _profile_payload(body), is_put=True,
        ip_address=_client_ip(request), actor_user_id=user.id,
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
    profile = await service.update(
        user.id, _profile_payload(body), is_put=False,
        ip_address=_client_ip(request), actor_user_id=user.id,
    )
    return profile_to_dict(profile)


@router.get("/users/{user_id}/profile")
async def get_user_profile(
    user_id: str,
    response: Response,
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    workspace_id: str | None = Depends(get_optional_workspace_id),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    """Redacted co-member projection, or the full editable profile for a caller
    holding `profile:update` on a workspace the target also belongs to."""
    service = ProfileService(db, container.bus)
    if await can_target_profile_update(user_id, response, db, principal, workspace_id):
        target = await db.get(User, user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="user or profile not found")
        profile = await service.get_or_create(user_id)
        # avatar_url lives on the user row, not the profile, and is editable here.
        return {**profile_to_dict(profile), "avatar_url": target.avatar_url}
    proj = await service.get_public_projection(
        user_id, viewer=principal.user, is_superuser=principal.is_deployment_admin
    )
    if proj is None:
        raise HTTPException(status_code=404, detail="user or profile not found")
    return proj

@router.patch("/users/{user_id}/profile")
async def update_user_profile(
    user_id: str,
    body: ProfileUpdate,
    request: Request,
    target_id: str = Depends(require_target_profile_update),
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
):
    profile = await ProfileService(db, container.bus).update(
        target_id, _profile_payload(body), is_put=False,
        ip_address=_client_ip(request), actor_user_id=principal.user.id,
    )
    return profile_to_dict(profile)

def _preferences_response(prefs) -> dict:
    return {
        "channels": {p.type: p.channel for p in prefs if p.type != DIGEST_TYPE},
        "digest_enabled": next((p.digest_enabled for p in prefs if p.type == DIGEST_TYPE), False),
    }

@router.get("/users/{user_id}/notification-preferences")
async def get_user_notification_preferences(
    user_id: str,
    target_id: str = Depends(require_target_profile_update),
    db: AsyncSession = Depends(get_db),
):
    return _preferences_response(await NotificationService(db).get_preferences(target_id))

@router.put("/users/{user_id}/notification-preferences")
async def update_user_notification_preferences(
    user_id: str,
    body: NotificationPreferencesUpdate,
    target_id: str = Depends(require_target_profile_update),
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
        await service.upsert_channels(target_id, body.channels)
    if body.digest_enabled is not None:
        await service.set_digest(target_id, body.digest_enabled)
    return _preferences_response(await service.get_preferences(target_id))

@router.get("/users/{user_id}/sessions", response_model=list[SessionRead])
async def list_user_sessions(
    user_id: str,
    target_id: str = Depends(require_target_profile_update),
    db: AsyncSession = Depends(get_db),
):
    """Live sessions of the target. A delegated view has no "current" session —
    the caller's own session belongs to a different user."""
    now = now_utc()
    rows = await AuthService(db).list_sessions(target_id)
    return [
        session_to_dict(r, current=False)
        for r in rows
        if r.revoked_at is None and ensure_utc(r.expires_at) >= now
    ]

@router.delete("/users/{user_id}/sessions", status_code=204)
async def revoke_all_user_sessions(
    request: Request,
    target_id: str = Depends(require_target_profile_update),
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    await AuthService(db, container.bus).revoke_other_sessions(
        target_id,
        current_session_id=None,
        ip_address=_client_ip(request),
        actor_user_id=principal.user.id,
    )

@router.delete("/users/{user_id}/sessions/{session_id}", status_code=204)
async def revoke_user_session(
    user_id: str,
    session_id: str,
    request: Request,
    target_id: str = Depends(require_target_profile_update),
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    try:
        await AuthService(db, container.bus).revoke_session(
            target_id,
            session_id,
            current_session_id=principal.session_id if target_id == principal.user.id else None,
            ip_address=_client_ip(request),
            actor_user_id=principal.user.id,
        )
    except AuthError as exc:
        if str(exc) == "cannot revoke the current session":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from None
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from None

@router.post("/users/{user_id}/password", status_code=204)
async def set_user_password(
    user_id: str,
    body: MemberPasswordUpdate,
    request: Request,
    target_id: str = Depends(require_target_profile_update),
    principal: AuthPrincipal = Depends(resolve_auth_principal),
    workspace_id: str = Depends(get_current_workspace_id),
    db: AsyncSession = Depends(get_db),
    container=Depends(get_container),
) -> None:
    """Set the target's password, revoking every session they hold.

    Self, the workspace owner and superusers are refused: overwriting their
    password is account takeover, not profile editing, and their own settings
    already cover it with a proof the caller holds (current password / 2FA).
    """
    if target_id == principal.user.id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "use /auth/change-password for your own password"
        )
    target = await db.get(User, target_id)
    if target is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user or profile not found")
    if target.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot change a superuser's password")
    membership = await WorkspaceService(db).get_membership(workspace_id, target_id)
    if membership is not None and membership[1].name == "owner":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "cannot change the workspace owner's password"
        )
    await AuthService(db, container.bus).change_password(
        target, body.new_password,
        ip_address=_client_ip(request), actor_user_id=principal.user.id,
    )


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
