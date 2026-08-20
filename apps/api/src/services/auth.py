from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.core.security.password import PasswordHasher
from src.core.security.tokens import OpaqueToken, create_access_token
from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.workspace import RefreshToken, User
from src.settings import settings

logger = logging.getLogger(__name__)


class AuthError(Exception):
    pass


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    token_type: str = "Bearer"
    expires_in: int = 900


class AuthService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    # ----------------------------------------------------------------- users

    async def get_user(self, user_id: str) -> User | None:
        return await self._session.get(User, user_id)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email.lower())
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def register(
        self,
        *,
        email: str,
        password: str | None,
        display_name: str,
        ip_address: str | None = None,
    ) -> User:
        email = email.lower()
        if await self.get_by_email(email):
            raise AuthError("an account with this email already exists")
        user = User(
            email=email,
            password_hash=PasswordHasher.hash(password) if password else None,
            display_name=display_name,
        )
        self._session.add(user)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.register",
            actor_user_id=user.id,
            details={"email": user.email, "display_name": user.display_name},
            ip_address=ip_address,
        )
        return user

    async def upsert_oauth_user(
        self, *, provider: str, subject: str, email: str, display_name: str
    ) -> User:
        """Find or create a user for an OAuth identity. Links by verified email."""
        user = await self.get_by_email(email)
        if user is None:
            user = User(email=email.lower(), password_hash=None, display_name=display_name)
            self._session.add(user)
            await self._session.commit()
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user.id,
                action="user.register",
                actor_user_id=user.id,
                details={"email": user.email, "provider": provider, "subject": subject},
            )
        return user

    # ------------------------------------------------------------------ auth

    async def login_password(
        self, email: str, password: str, *, ip_address: str | None = None
    ) -> User:
        user = await self.get_by_email(email)
        if user is None or user.password_hash is None:
            raise AuthError("invalid credentials")
        if not PasswordHasher.verify(password, user.password_hash):
            raise AuthError("invalid credentials")
        if not user.is_active:
            raise AuthError("account is disabled")
        user.last_login_at = now_utc()
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.login",
            actor_user_id=user.id,
            details={"email": user.email},
            ip_address=ip_address,
        )
        return user

    async def issue_tokens(self, user: User) -> TokenPair:
        refresh = OpaqueToken.generate()
        self._session.add(
            RefreshToken(
                user_id=user.id,
                token_hash=OpaqueToken.hash(refresh),
                expires_at=now_utc() + timedelta(days=settings.refresh_token_expire_days),
            )
        )
        await self._session.commit()
        return TokenPair(
            access_token=create_access_token(user.id),
            refresh_token=refresh,
        )

    async def rotate_refresh(
        self, refresh_token: str, *, ip_address: str | None = None
    ) -> TokenPair:
        """Rotate a refresh token: revoke the presented one, issue a new pair."""
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == OpaqueToken.hash(refresh_token)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            raise AuthError("invalid refresh token")
        if ensure_utc(row.expires_at) < now_utc():
            raise AuthError("refresh token expired")
        user = await self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise AuthError("account is disabled")
        row.revoked_at = now_utc()
        await self._session.commit()
        pair = await self.issue_tokens(user)
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.token_refresh",
            actor_user_id=user.id,
            details={"email": user.email},
            ip_address=ip_address,
        )
        return pair

    async def revoke_refresh(self, refresh_token: str, *, ip_address: str | None = None) -> None:
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == OpaqueToken.hash(refresh_token)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is not None:
            user_id = row.user_id
            row.revoked_at = now_utc()
            await self._session.commit()
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user_id,
                action="user.logout",
                actor_user_id=user_id,
                ip_address=ip_address,
            )
