from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security.tokens import decode_access_token
from src.db.session import get_db
from src.models.api_key import ApiKey
from src.models.workspace import User, Workspace
from src.services.api_keys import ApiKeyService
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService

logger = logging.getLogger(__name__)

bearer = HTTPBearer(auto_error=False)


def get_container(request: Request):
    return request.app.state.container


@dataclass
class AuthPrincipal:
    """Authenticated caller: either a session user or a workspace API key.

    API keys act on behalf of their creator's user account, so `user` is always
    set; `api_key` is set when the request was authenticated with an opaque
    key, in which case its own permission list governs authorization.
    """

    user: User
    api_key: ApiKey | None = None
    session_id: str | None = None


async def resolve_auth_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> AuthPrincipal:
    """Authenticate a request via a JWT session token or an API key.

    Resolved once per request (FastAPI caches sub-dependencies) and shared by
    get_current_user and require_permission, so both always agree on the
    authentication method.
    """
    if credentials is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing credentials")
    # JWT session tokens take precedence; API keys are the fallback.
    try:
        payload = decode_access_token(credentials.credentials)
    except Exception:
        payload = None
    if payload is not None:
        user_id = payload.get("sub")
        if not user_id or payload.get("type") != "access":
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token type")
        user = await AuthService(db).get_user(user_id)
        if user is None or not user.is_active:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or disabled")
        session_id = payload.get("sid")
        if session_id is not None and not await AuthService(db).is_session_active(
            session_id, user_id
        ):
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "session revoked")
        return AuthPrincipal(user=user, session_id=session_id)
    # Not a JWT — try an opaque API key.
    api_key = await ApiKeyService(db).authenticate(credentials.credentials)
    if api_key is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired credentials")
    user = await AuthService(db).get_user(api_key.created_by_user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user not found or disabled")
    return AuthPrincipal(user=user, api_key=api_key)


async def get_current_user(
    principal: AuthPrincipal = Depends(resolve_auth_principal),
) -> User:
    return principal.user


async def require_superuser(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    """Gate deployment-wide administration (e.g. global scheduled jobs)."""
    if not user.is_superuser:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "superuser access required")
    return user


async def get_current_workspace_id(
    x_workspace_id: Annotated[UUID | None, Header(alias="X-Workspace-ID")] = None,
) -> str:
    """Required X-Workspace-ID header, canonicalised to str.

    The UUID annotation makes FastAPI reject a malformed header as 422. The return
    type stays str deliberately: StringUUID round-trips UUID columns back to str, so
    widening it to UUID would silently break the api_key.workspace_id equality
    checks in require_key_permission/require_permission.
    """
    if not x_workspace_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Workspace-ID header is required")
    return str(x_workspace_id)


async def get_optional_workspace_id(
    x_workspace_id: Annotated[UUID | None, Header(alias="X-Workspace-ID")] = None,
) -> str | None:
    """Like get_current_workspace_id, but optional.

    Used by routes that are user-scoped for session users (notifications,
    received invitations, workspace listing) but become workspace-scoped the
    moment an API key is presented.
    """
    return str(x_workspace_id) if x_workspace_id is not None else None


def _check_key_quota(api_key: ApiKey) -> None:
    """Reject keys that exhausted their usage quota (None = unlimited)."""
    if api_key.usage_quota is not None and api_key.usage_count >= api_key.usage_quota:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "api key quota exceeded")


def _quota_headers(api_key: ApiKey) -> dict[str, str]:
    """Quota/remaining headers for key-authenticated responses (empty = unlimited)."""
    if api_key.usage_quota is None:
        return {}
    return {
        "X-API-Key-Quota": str(api_key.usage_quota),
        "X-API-Key-Remaining": str(max(0, api_key.usage_quota - api_key.usage_count)),
    }


async def record_key_use(api_key: ApiKey, db: AsyncSession, response: Response) -> None:
    """Quota-check + touch + headers for key-authenticated requests.

    Shared by require_key_permission and require_permission so the two
    branches cannot drift."""
    _check_key_quota(api_key)
    await ApiKeyService(db).touch(api_key)
    for k, v in _quota_headers(api_key).items():
        response.headers[k] = v


def require_key_permission(permission: str):
    """Enforce a permission for API-key requests only.

    Session-user flows that are naturally user-scoped (notifications, received
    invitations, workspace listing) keep their existing behavior; API-key
    requests are always workspace-scoped and must prove the permission against
    the key's own permission list — never the key owner's role.
    """

    async def checker(
        response: Response,
        db: Annotated[AsyncSession, Depends(get_db)],
        principal: AuthPrincipal = Depends(resolve_auth_principal),
        workspace_id: str | None = Depends(get_optional_workspace_id),
    ):
        if principal.api_key is None:
            return None
        api_key = principal.api_key
        if not workspace_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Workspace-ID header is required")
        if api_key.workspace_id != workspace_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "api key is not scoped to this workspace"
            )
        if "*" in api_key.permissions or permission in api_key.permissions:
            await record_key_use(api_key, db, response)
            return None
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"missing permission: {permission}"
        ) from None

    return checker


async def resolve_membership(
    db: Annotated[AsyncSession, Depends(get_db)],
    user=Depends(get_current_user),
    workspace_id: str = Depends(get_current_workspace_id),
):
    membership = await WorkspaceService(db).get_membership(workspace_id, user.id)
    if membership is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
    return membership


def require_permission(permission: str):
    async def checker(
        response: Response,
        db: Annotated[AsyncSession, Depends(get_db)],
        principal: AuthPrincipal = Depends(resolve_auth_principal),
        workspace_id: str = Depends(get_current_workspace_id),
    ):
        # API-key requests are authorized by the key's own permission list,
        # never by the key owner's role — that way a leaked key is limited to
        # the exact permissions it was minted with.
        if principal.api_key is not None:
            api_key = principal.api_key
            if api_key.workspace_id != workspace_id:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "api key is not scoped to this workspace"
                )
            if "*" in api_key.permissions or permission in api_key.permissions:
                await record_key_use(api_key, db, response)
                return None
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing permission: {permission}"
            ) from None
        service = WorkspaceService(db)
        membership = await service.get_membership(workspace_id, principal.user.id)
        if membership is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
        _, role = membership
        if "*" in role.permissions or permission in role.permissions:
            return None
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"missing permission: {permission}"
        ) from None

    return checker


async def require_existing_workspace(
    workspace_id: UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """404 on missing workspaces before membership checks run.

    Opt-in for single-workspace routes (GET/PATCH/DELETE /workspaces/{id}):
    once delete cascades WorkspaceMember rows, the membership check inside
    require_permission would 403 on a deleted workspace instead of the
    contract's 404. The shared require_permission is untouched. Runs after
    get_current_user, so only authenticated callers can distinguish 404
    (missing) from 403 (exists, not a member); workspace ids are
    unguessable UUIDs, so this tradeoff is intentional.
    """
    if await db.get(Workspace, workspace_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "workspace not found")


async def authenticate_websocket_token(db: AsyncSession, token: str | None) -> User | None:
    """Validate a WebSocket access token.

    Returns the authenticated user, or None when the token is missing/invalid
    or the account is inactive. The caller owns the DB session and must close
    it before the socket loop starts — WebSockets stay open for minutes to
    hours, and holding a pool connection for their lifetime would exhaust the
    pool after ~15 open sockets.
    """
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except Exception:
        return None
    user_id = payload.get("sub", "")
    user = await AuthService(db).get_user(user_id)
    if user is None or not user.is_active:
        return None
    session_id = payload.get("sid")
    if session_id is not None and not await AuthService(db).is_session_active(session_id, user_id):
        return None
    return user
