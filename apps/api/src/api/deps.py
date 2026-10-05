from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import format_datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import now_utc
from src.core.permissions import PROFILE_UPDATE
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


def uuid_or_404(value: str, label: str) -> str:
    # StringUUID's bind processor raises ValueError (-> 500) on a malformed id,
    # so validate before it reaches the query.
    try:
        uuid.UUID(value)
    except ValueError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found") from None
    return value


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

    @property
    def is_deployment_admin(self) -> bool:
        """Superuser power, and only session auth ever has it.

        Every route-level deployment-wide gate reads this property rather
        than `user.is_superuser`: an API key resolves to its creator's
        `User`, so testing that field would hand a leaked key admin power.
        Keys are workspace-scoped credentials, never deployment admins.

        One service below the gate re-checks the bare flag —
        `ProfileService.delete_account_superuser` reads `actor.is_superuser`
        on the `User` it deletes with. `require_superuser` is the only route
        to it, so a key principal never arrives; the re-check is redundant
        defence in depth, kept because the service is callable directly."""
        return self.api_key is None and self.user.is_superuser


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


async def require_session_user(
    principal: AuthPrincipal = Depends(resolve_auth_principal),
) -> User:
    """Reject API-key principals. The single session-only gate.

    An API key carries its creator's role into the service layer, so a route
    whose real authority check is a *role* check (not a permission) would let a
    narrowly scoped key exercise owner-level powers. Two families need an
    interactive session: owner-level operations (ownership transfer), and
    self-service routes that read or change the caller's own account — the
    `/me` family (profile writes, data export, account deletion), 2FA, sessions
    and the password. No permission list covers any of them, so the key would be
    the only thing deciding access. (`GET /me/profile` and `GET /auth/me` stay
    readable by a key: they report the caller's own identity.)

    This list is not exhaustive. `POST /auth/resend-verification` is
    deliberately left key-reachable: it depends on `get_current_user`, holds no
    permission list, changes no authority, and mails the address it already
    knows. It is also neither rate-limited (login, forgot and reset call
    `get_auth_limiter()`) nor quota-charged — it never reaches
    `record_key_use` — so a key can trigger a mail per call without spending
    key quota.
    ponytail: that mail path is unmetered by design today; put
    `get_auth_limiter()` on the route when the ceiling has to be closed.
    """
    if principal.api_key is not None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "api keys cannot perform this action")
    return principal.user


async def require_superuser(
    principal: AuthPrincipal = Depends(resolve_auth_principal),
) -> User:
    """Gate deployment-wide administration (e.g. global scheduled jobs).

    Session-only: API keys never carry deployment-wide power, even when
    minted by a superuser, so key-authenticated requests always 403 here.
    Use this dependency for every deployment-wide route — `/admin/*` and
    the `/jobs/global*` family are session superuser only.

    The 403 detail names the supported path rather than the caller's
    authority: a key is told deployment administration needs a session, a
    session user without the flag is told the privilege is missing. Neither
    answer reveals anything the status code does not.

    Routes that mix superuser and co-member access pass
    `principal.is_deployment_admin` to their service instead, so an API key
    can never reach a service superuser branch."""
    if not principal.is_deployment_admin:
        raise deployment_admin_denied(principal)
    return principal.user


def deployment_admin_denied(principal: AuthPrincipal) -> HTTPException:
    """Build the 403 for a deployment-wide gate. Shared with the routes that
    resolve their own check, so one denial of the same kind never reaches the
    caller as two different messages."""
    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        "deployment administration is not available to API keys"
        if principal.api_key is not None
        else "superuser access required",
    )


async def resolve_or_deny(principal: AuthPrincipal, lookup, missing_detail: str):
    """Resolve a record, or raise the only answer the caller may get.

    No key is ever a deployment admin (`AuthPrincipal.is_deployment_admin`), so
    nothing outside its own workspace is readable by one — a deployment-wide
    record included. Answering a miss with 404 and a real record with 403 turns
    that pair into an existence oracle on a surface the key is denied, so a
    miss raises the same deployment-admin 403 the gate would. The gate gives a
    key that one answer for every other record too.

    A session caller keeps the 404: a browser session has to tell an id that
    matches nothing apart from one it may not read, and that is the single
    distinction it is allowed to make.
    """
    record = await lookup
    if record is None:
        if principal.api_key is not None:
            raise deployment_admin_denied(principal)
        raise HTTPException(status.HTTP_404_NOT_FOUND, missing_detail)
    return record


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


def _quota_headers(api_key: ApiKey, now: datetime) -> dict[str, str]:
    """Quota/remaining/reset headers for key-authenticated responses.

    Empty = unlimited key. All three are per calendar month: Remaining counts
    the uses left in the current window, not the lifetime total, and Reset is
    the instant the window rolls over, so a client blocked at the quota knows
    when it recovers.
    """
    if api_key.usage_quota is None:
        return {}
    month = now.month
    reset = datetime(now.year + month // 12, month % 12 + 1, 1, tzinfo=UTC)
    return {
        "X-API-Key-Quota": str(api_key.usage_quota),
        "X-API-Key-Remaining": str(max(0, api_key.usage_quota - api_key.usage_window_count)),
        "X-API-Key-Window-Reset": format_datetime(reset, usegmt=True),
    }


async def record_key_use(api_key: ApiKey, db: AsyncSession, response: Response) -> None:
    """Count the use + emit quota headers for key-authenticated requests.

    Invariant: every branch that authorizes an API key must charge through
    this function, or the key is unmetered — a hand-rolled `api_key is not
    None` branch that skips it is the bug this guards against. The 403 comes
    from the conditional UPDATE's rowcount, never from a pre-read, so two
    concurrent requests cannot both spend the last unit.

    Shared by both permission dependencies and the jobs routes, so no branch
    that authorizes a key can drift into charging differently. One clock read
    feeds the rollover, the counter and the reset header, so they cannot
    disagree. The rejection carries the same headers, which a client that has
    run out needs more than one that has not.
    `response` is what makes the charge observable (the quota headers); a
    caller that omits it still charges, but cannot see the balance it just
    spent.
    """
    now = now_utc()
    if not await ApiKeyService(db).record_use(api_key, now):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "api key quota exceeded",
            headers=_quota_headers(api_key, now),
        )
    for k, v in _quota_headers(api_key, now).items():
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
        membership = await WorkspaceService(db).get_membership(
            workspace_id, principal.user.id, active_only=True
        )
        if membership is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
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
    membership = await WorkspaceService(db).get_membership(workspace_id, user.id, active_only=True)
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
            membership = await WorkspaceService(db).get_membership(
                workspace_id, principal.user.id, active_only=True
            )
            if membership is None:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "you are not a member of this workspace"
                )
            if "*" in api_key.permissions or permission in api_key.permissions:
                await record_key_use(api_key, db, response)
                return None
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, f"missing permission: {permission}"
            ) from None
        service = WorkspaceService(db)
        membership = await service.get_membership(workspace_id, principal.user.id, active_only=True)
        if membership is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "you are not a member of this workspace")
        _, role = membership
        if "*" in role.permissions or permission in role.permissions:
            return None
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, f"missing permission: {permission}"
        ) from None

    return checker


async def can_target_profile_update(
    user_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthPrincipal, Depends(resolve_auth_principal)],
    workspace_id: Annotated[str | None, Depends(get_optional_workspace_id)],
) -> bool:
    """True when the caller may read and edit `user_id`'s full profile.

    Self and deployment admins always may. Everyone else needs `profile:update`
    in `X-Workspace-ID` plus an active membership for the target in that same
    workspace, so the scope never reaches a user outside the caller's own
    workspace. Without the header there is no workspace to evaluate the
    permission against, so only self and deployment admins pass — the redacted
    cross-user read keeps working for plain co-members.

    Never raises for a refusal: the read path falls back to the redacted
    projection, which is the safe answer. A server-side failure is not a refusal
    and propagates. `require_target_profile_update` is the strict variant.
    """
    try:
        return await _target_profile_update(user_id, response, db, principal, workspace_id)
    except HTTPException as exc:
        if exc.status_code >= status.HTTP_500_INTERNAL_SERVER_ERROR:
            raise
        return False


async def _target_profile_update(
    user_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthPrincipal, Depends(resolve_auth_principal)],
    workspace_id: Annotated[str | None, Depends(get_optional_workspace_id)],
) -> bool:
    """The strict check behind both entry points; raises 403/404 on refusal."""
    # A malformed id can never name a member, so it 404s before any UUID bind.
    uuid_or_404(user_id, "user")
    if principal.is_deployment_admin or principal.user.id == user_id:
        # This branch skips the membership lookup, so it is also the only path
        # where nothing has checked that the target is a real user: without the
        # lookup a superuser id writes an orphan `user_profiles` /
        # `notification_preferences` row, an FK violation on Postgres. Self
        # hits the session identity map, so it costs no query.
        if await db.get(User, user_id) is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found")
        return True
    if workspace_id is None:
        return False
    await require_permission(PROFILE_UPDATE)(response, db, principal, workspace_id)
    # Any membership row that counts for access, i.e. an *active* one: a
    # suspended member is out of the workspace's editable set, so the target
    # lookup 404s exactly like a user who was never a member. The caller still
    # passed an active-membership check of their own inside require_permission.
    membership = await WorkspaceService(db).get_membership(workspace_id, user_id)
    if membership is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "user not found in this workspace")
    return True


async def require_target_profile_update(
    user_id: str,
    response: Response,
    db: Annotated[AsyncSession, Depends(get_db)],
    principal: Annotated[AuthPrincipal, Depends(resolve_auth_principal)],
    workspace_id: Annotated[str, Depends(get_current_workspace_id)],
) -> str:
    """Route guard for every target-scoped profile route.

    Declaring this dependency is all a new profile tab has to do to inherit the
    authorization contract; a missing target membership is a 404 so the route
    never confirms whether a user exists outside the caller's workspace.
    """
    await _target_profile_update(user_id, response, db, principal, workspace_id)
    return user_id


async def require_existing_workspace(
    workspace_id: str,
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
