from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, WebSocket, WebSocketException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security.tokens import decode_access_token
from src.db.session import get_db
from src.models.api_key import ApiKey
from src.models.workspace import User
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
        return AuthPrincipal(user=user)
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


async def get_current_workspace_id(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
) -> str:
    if not x_workspace_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "X-Workspace-ID header is required")
    return x_workspace_id


async def get_optional_workspace_id(
    x_workspace_id: Annotated[str | None, Header(alias="X-Workspace-ID")] = None,
) -> str | None:
    """Like get_current_workspace_id, but optional.

    Used by routes that are user-scoped for session users (notifications,
    received invitations, workspace listing) but become workspace-scoped the
    moment an API key is presented.
    """
    return x_workspace_id


def require_key_permission(permission: str):
    """Enforce a permission for API-key requests only.

    Session-user flows that are naturally user-scoped (notifications, received
    invitations, workspace listing) keep their existing behavior; API-key
    requests are always workspace-scoped and must prove the permission against
    the key's own permission list — never the key owner's role.
    """

    async def checker(
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
            await ApiKeyService(db).touch(api_key)
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
                await ApiKeyService(db).touch(api_key)
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


async def websocket_auth(websocket: WebSocket, db: Annotated[AsyncSession, Depends(get_db)]):
    token = websocket.query_params.get("token")
    if not token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="missing token")
    try:
        payload = decode_access_token(token)
    except Exception as exc:
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION, reason="invalid token"
        ) from exc
    user = await AuthService(db).get_user(payload.get("sub", ""))
    if user is None or not user.is_active:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="invalid user")
    # Release the DB session before the socket loop starts. WebSockets stay
    # open for a long time (minutes to hours); holding a get_db session (and
    # its pool connection) for the socket's lifetime would exhaust the
    # connection pool after ~15 open sockets and 500 every API request.
    await db.close()
    return user
