from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.core.security.password import PasswordHasher
from src.core.security.tokens import OpaqueToken, create_access_token
from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.workspace import AuthToken, RefreshToken, User
from src.services.profile_helpers import format_display_name
from src.settings import settings

RESET_TOKEN_TTL = timedelta(hours=1)
VERIFY_TOKEN_TTL = timedelta(hours=24)

RESET_PURPOSE = "password_reset"
VERIFY_PURPOSE = "email_verification"

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

    @staticmethod
    def _format_display_name(
        first_name: str | None, last_name: str | None, fallback: str | None = None
    ) -> str:
        """Format as 'First L.' — delegates to profile_helpers for single source."""
        return format_display_name(first_name, last_name, fallback)

    @staticmethod
    def _split_display_name(display_name: str | None) -> tuple[str | None, str | None]:
        if not display_name:
            return None, None
        parts = display_name.strip().split()
        if len(parts) == 1:
            return parts[0], None
        return parts[0], " ".join(parts[1:])

    async def register(
        self,
        *,
        email: str,
        password: str | None,
        first_name: str | None = None,
        last_name: str | None = None,
        display_name: str | None = None,
        ip_address: str | None = None,
    ) -> User:
        email = email.lower()
        if not settings.auth_allow_registration:
            raise AuthError("registration is disabled")
        if await self.get_by_email(email):
            raise AuthError("an account with this email already exists")
        # Derive names — prefer explicit first/last, fallback to splitting display_name
        if not first_name and not last_name and display_name:
            first_name, last_name = self._split_display_name(display_name)
        if not first_name:
            if display_name:
                # Fallback: use display_name as first_name for legacy single-name registrations
                first_name = display_name.strip().split()[0] if display_name.strip() else None
            if not first_name:
                raise AuthError("first_name is required")
        display = self._format_display_name(first_name, last_name, display_name) or (
            display_name or "User"
        )
        user = User(
            email=email,
            password_hash=PasswordHasher.hash(password) if password else None,
            display_name=display,
            is_superuser=self._is_superadmin_email(email),
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
        # Auto-provision profile with names (best-effort, idempotent)
        try:
            from src.services.profiles import ProfileService

            profile = await ProfileService(self._session, self._bus).get_or_create(user.id)
            # Populate profile first/last if provided
            if first_name or last_name:
                from sqlalchemy.orm.attributes import flag_modified  # noqa: F401

                if first_name and not profile.first_name:
                    profile.first_name = first_name
                if last_name and not profile.last_name:
                    profile.last_name = last_name
                await self._session.commit()
            elif display_name:
                # Split display_name into profile for backward compat
                fn, ln = self._split_display_name(display_name)
                if fn or ln:
                    if fn and not profile.first_name:
                        profile.first_name = fn
                    if ln and not profile.last_name:
                        profile.last_name = ln
                    await self._session.commit()
        except Exception:
            logger.exception("failed to provision profile for user %s", user.id)
        return user

    async def upsert_oauth_user(
        self,
        *,
        provider: str,
        subject: str,
        email: str,
        display_name: str | None = None,
        first_name: str | None = None,
        last_name: str | None = None,
    ) -> User:
        """Find or create a user for an OAuth identity.

        Links by (provider, subject) first so identity survives email changes;
        falls back to verified email on first connect, so multiple providers
        sharing an email link to the same user. New users are rejected when
        AUTH_ALLOW_REGISTRATION is off — before any insert."""
        from src.models.oauth import OAuthAccount

        stmt = select(OAuthAccount).where(
            OAuthAccount.provider == provider, OAuthAccount.subject == subject
        )
        link = (await self._session.execute(stmt)).scalar_one_or_none()
        if link is not None:
            user = await self._session.get(User, link.user_id)
            if user is not None:
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
                    details={"email": user.email, "provider": provider},
                )
                return user
        # Derive first/last from display_name if not provided (OAuth often gives display_name)
        if not first_name and not last_name and display_name:
            first_name, last_name = self._split_display_name(display_name)
        display = self._format_display_name(first_name, last_name, display_name) or (
            display_name or email.split("@")[0]
        )
        user = await self.get_by_email(email)
        if user is None:
            if not settings.auth_allow_registration:
                raise AuthError("registration is disabled")
            email = email.lower()
            user = User(
                email=email,
                password_hash=None,
                display_name=display,
                is_superuser=self._is_superadmin_email(email),
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
                details={"email": user.email, "provider": provider, "subject": subject},
            )
            try:
                from src.services.profiles import ProfileService

                profile = await ProfileService(self._session, self._bus).get_or_create(user.id)
                if first_name and not profile.first_name:
                    profile.first_name = first_name
                if last_name and not profile.last_name:
                    profile.last_name = last_name
                if (first_name or last_name) and (profile.first_name or profile.last_name):
                    await self._session.commit()
            except Exception:
                logger.exception("failed to provision profile for oauth user %s", user.id)
        else:
            if not user.is_active:
                raise AuthError("account is disabled")
        self._session.add(OAuthAccount(user_id=user.id, provider=provider, subject=subject))
        from sqlalchemy.exc import IntegrityError

        try:
            await self._session.commit()
        except IntegrityError:
            await self._session.rollback()
            existing = (await self._session.execute(stmt)).scalar_one_or_none()
            if existing is not None and existing.user_id != user.id:
                raise AuthError("this sign-in is already linked to another account") from None
            user = await self._session.get(User, existing.user_id) if existing else user
            if user is None or not user.is_active:
                raise AuthError("account is disabled") from None
        user.last_login_at = now_utc()
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.login",
            actor_user_id=user.id,
            details={"email": user.email, "provider": provider},
        )
        return user

    def _is_superadmin_email(self, email: str) -> bool:
        """The SUPERADMIN_EMAIL account bootstraps as superuser on registration."""
        configured = settings.superadmin_email.strip().lower()
        return bool(configured) and email == configured

    # ------------------------------------------------------------------ auth

    async def login_password(
        self, email: str, password: str, *, ip_address: str | None = None
    ) -> User:
        if not settings.auth_password_enabled:
            raise AuthError("password login is disabled")
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

    async def issue_tokens(
        self,
        user: User,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
        two_factor_verified: bool = False,
    ) -> TokenPair:
        refresh = OpaqueToken.generate()
        row = RefreshToken(
            user_id=user.id,
            token_hash=OpaqueToken.hash(refresh),
            expires_at=now_utc() + timedelta(days=settings.refresh_token_expire_days),
            two_factor_verified_at=now_utc() if two_factor_verified else None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        self._session.add(row)
        await self._session.commit()
        return TokenPair(
            access_token=create_access_token(user.id, session_id=row.id),
            refresh_token=refresh,
        )

    async def is_session_active(self, session_id: str, user_id: str) -> bool:
        """True when the session row exists, belongs to the user, and is live."""
        row = await self._session.get(RefreshToken, session_id)
        if row is None or row.user_id != user_id or row.revoked_at is not None:
            return False
        return ensure_utc(row.expires_at) >= now_utc()

    async def is_session_two_factor_verified(self, session_id: str, user_id: str) -> bool:
        """True when the session cleared a 2FA challenge. False for unknown or
        password-only sessions — the workspace `require_2fa` gate fails closed."""
        row = await self._session.get(RefreshToken, session_id)
        if row is None or row.user_id != user_id or row.revoked_at is not None:
            return False
        return row.two_factor_verified_at is not None

    async def mark_session_two_factor_verified(self, session_id: str, user_id: str) -> None:
        """Stamp an already-live session as 2FA-verified.

        Called when a user enables 2FA from inside an existing session: they
        just proved possession of the secret with a valid code, which is the
        same evidence the login challenge collects. Without this, a user who
        opts in mid-session is bounced to the setup page forever, because the
        session that enabled 2FA never recorded having passed it.
        """
        row = await self._session.get(RefreshToken, session_id)
        if row is None or row.user_id != user_id or row.revoked_at is not None:
            return
        if row.two_factor_verified_at is not None:
            return
        row.two_factor_verified_at = now_utc()
        await self._session.commit()

    async def rotate_refresh(
        self,
        refresh_token: str,
        *,
        ip_address: str | None = None,
        user_agent: str | None = None,
    ) -> TokenPair:
        """Rotate a refresh token: revoke the presented one, issue a new pair."""
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.token_hash == OpaqueToken.hash(refresh_token))
            .with_for_update()
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
        # Carry the 2FA verdict onto the successor row. Without this a refresh
        # would reset the session to password-only and lock the user out of any
        # workspace that sets require_2fa.
        verified_at = row.two_factor_verified_at
        await self._session.commit()
        pair = await self.issue_tokens(
            user,
            ip_address=ip_address,
            user_agent=user_agent,
            two_factor_verified=verified_at is not None,
        )
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

    async def revoke_session(
        self,
        user_id: str,
        session_id: str,
        *,
        current_session_id: str | None,
        ip_address: str | None = None,
    ) -> None:
        """Revoke one session; raises AuthError when it is current or unknown."""
        if session_id == current_session_id:
            raise AuthError("cannot revoke the current session")
        rows = await self.list_sessions(user_id)
        row = next((r for r in rows if r.id == session_id), None)
        if row is None:
            raise AuthError("session not found")
        if row.revoked_at is None:
            row.revoked_at = now_utc()
            await self._session.commit()
            logger.info("session revoked user=%s session=%s", user_id, session_id)
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user_id,
                action="user.session_revoked",
                actor_user_id=user_id,
                details={"session_id": session_id},
                ip_address=ip_address,
            )

    async def revoke_other_sessions(
        self, user_id: str, *, current_session_id: str | None, ip_address: str | None = None
    ) -> int:
        """Revoke every live session except the current one; returns the count."""
        rows = await self.list_sessions(user_id)
        now = now_utc()
        count = 0
        for r in rows:
            if r.id == current_session_id:
                continue
            if r.revoked_at is None and ensure_utc(r.expires_at) >= now:
                r.revoked_at = now
                count += 1
        if count:
            await self._session.commit()
            logger.info("other sessions revoked user=%s count=%d", user_id, count)
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user_id,
                action="user.sessions_revoked",
                actor_user_id=user_id,
                details={"revoked_count": count},
                ip_address=ip_address,
            )
        return count

    async def list_sessions(self, user_id: str) -> list[RefreshToken]:
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def get_user_by_refresh_token(self, refresh_token: str) -> User | None:
        """Return the owner of a refresh token (revoked or not), or None."""
        stmt = select(RefreshToken).where(
            RefreshToken.token_hash == OpaqueToken.hash(refresh_token)
        )
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return await self._session.get(User, row.user_id)

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

    # ------------------------------------------- password reset + verification

    def _mint_token(self, user_id: str, purpose: str, ttl: timedelta) -> str:
        raw = OpaqueToken.generate()
        self._session.add(
            AuthToken(
                user_id=user_id,
                purpose=purpose,
                token_hash=OpaqueToken.hash(raw),
                expires_at=now_utc() + ttl,
            )
        )
        return raw

    async def _consume_token(self, raw: str, purpose: str) -> AuthToken:
        stmt = (
            select(AuthToken)
            .where(
                AuthToken.token_hash == OpaqueToken.hash(raw),
                AuthToken.purpose == purpose,
            )
            .with_for_update()
        )
        row = (await self._session.execute(stmt)).scalar_one_or_none()
        if row is None or row.consumed_at is not None:
            raise AuthError("invalid or expired token")
        if ensure_utc(row.expires_at) < now_utc():
            raise AuthError("invalid or expired token")
        row.consumed_at = now_utc()
        return row

    async def request_password_reset(
        self, email: str, *, ip_address: str | None = None
    ) -> str | None:
        """Mint a reset token; None when unknown (callers must not reveal which)."""
        user = await self.get_by_email(email)
        if user is None:
            return None
        now = now_utc()
        await self._session.execute(
            update(AuthToken)
            .where(
                AuthToken.user_id == user.id,
                AuthToken.purpose == RESET_PURPOSE,
                AuthToken.consumed_at.is_(None),
            )
            .values(consumed_at=now)
        )
        raw = self._mint_token(user.id, RESET_PURPOSE, RESET_TOKEN_TTL)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.password_reset_requested",
            actor_user_id=user.id,
            details={"email": user.email},
            ip_address=ip_address,
        )
        return raw

    async def reset_password(
        self, token: str, new_password: str, *, ip_address: str | None = None
    ) -> User:
        row = await self._consume_token(token, RESET_PURPOSE)
        user = await self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise AuthError("account is disabled")
        user.password_hash = PasswordHasher.hash(new_password)
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now_utc())
        )
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.password_reset_completed",
            actor_user_id=user.id,
            ip_address=ip_address,
        )
        return user

    async def change_password(
        self, user: User, new_password: str, *, ip_address: str | None = None
    ) -> User:
        """Set a new password hash and revoke every refresh session.

        Unlike revoke_other_sessions the current session dies too — the
        caller must force a re-login. Same write pair reset_password does."""
        user.password_hash = PasswordHasher.hash(new_password)
        await self._session.execute(
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user.id,
                RefreshToken.revoked_at.is_(None),
            )
            .values(revoked_at=now_utc())
        )
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.password_changed",
            actor_user_id=user.id,
            ip_address=ip_address,
        )
        return user

    async def request_verification(self, user: User) -> str:
        raw = self._mint_token(user.id, VERIFY_PURPOSE, VERIFY_TOKEN_TTL)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.email_verification_sent",
            actor_user_id=user.id,
            details={"email": user.email},
        )
        return raw

    async def verify_email(self, token: str) -> User:
        row = await self._consume_token(token, VERIFY_PURPOSE)
        user = await self._session.get(User, row.user_id)
        if user is None or not user.is_active:
            raise AuthError("account is disabled")
        user.email_verified_at = now_utc()
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.email_verified",
            actor_user_id=user.id,
        )
        return user
