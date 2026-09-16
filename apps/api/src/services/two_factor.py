from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import now_utc
from src.core.security.crypto import SecretCipher
from src.core.security.totp import (
    generate_backup_codes,
    generate_secret,
    hash_backup_code,
    otpauth_uri,
    secret_from_base32,
    secret_to_base32,
    verify,
)
from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.two_factor import UserTotpCredential
from src.models.workspace import RefreshToken, User
from src.settings import settings

logger = logging.getLogger(__name__)

# Setup secrets live only long enough to scan the QR (plaintext in memory,
# keyed by an opaque token, never persisted). ponytail: move to Redis/shared
# cache when the API scales past one replica.
SETUP_TTL = timedelta(minutes=10)
CHALLENGE_TTL = timedelta(minutes=5)
_pending_setups: dict[str, tuple[str, str, object]] = {}  # token -> (user_id, b32, expires)
_challenges: dict[str, tuple[str, object]] = {}  # token -> (user_id, expires)


class TwoFactorError(Exception):
    pass


def _prune(store: dict, now) -> None:
    for token in [t for t, (_, *_, exp) in store.items() if exp <= now]:
        del store[token]


class TwoFactorService:
    def __init__(
        self, session: AsyncSession, cipher: SecretCipher, bus: EventBus | None = None
    ) -> None:
        self._session = session
        self._cipher = cipher
        self._bus = bus

    async def get_credential(self, user_id: str) -> UserTotpCredential | None:
        return await self._session.get(UserTotpCredential, user_id)

    async def start_setup(self, user: User) -> dict:
        """Begin enrolment: fresh secret + otpauth URI. Enable requires a code."""
        if user.totp_enabled:
            raise TwoFactorError("two-factor authentication is already enabled")
        secret = generate_secret()
        b32 = secret_to_base32(secret)
        token = secrets.token_urlsafe(32)
        _prune(_pending_setups, now_utc())
        _pending_setups[token] = (user.id, b32, now_utc() + SETUP_TTL)
        issuer = settings.app_name
        return {
            "setup_token": token,
            "otpauth_uri": otpauth_uri(secret_b32=b32, email=user.email, issuer=issuer),
        }

    async def confirm_setup(self, user: User, *, setup_token: str, code: str) -> list[str]:
        """Verify the setup code, enable 2FA, return plaintext backup codes (once)."""
        _prune(_pending_setups, now_utc())
        pending = _pending_setups.pop(setup_token, None)
        if pending is None or pending[0] != user.id:
            raise TwoFactorError("setup session expired or invalid")
        secret = secret_from_base32(pending[1])
        counter = verify(secret, code)
        if counter is None:
            raise TwoFactorError("invalid code")
        codes = generate_backup_codes()
        cred = await self.get_credential(user.id)
        if cred is None:
            cred = UserTotpCredential(
                user_id=user.id,
                secret_ciphertext=self._cipher.encrypt(pending[1]),
                last_counter=counter,
                backup_codes=[hash_backup_code(c) for c in codes],
            )
            self._session.add(cred)
        else:
            cred.secret_ciphertext = self._cipher.encrypt(pending[1])
            cred.last_counter = counter
            cred.backup_codes = [hash_backup_code(c) for c in codes]
        user.totp_enabled = True
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.2fa_enabled",
            actor_user_id=user.id,
        )
        return codes

    async def disable(self, user: User) -> None:
        cred = await self.get_credential(user.id)
        if cred is not None:
            await self._session.delete(cred)
        user.totp_enabled = False
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=None,
            resource_type="user",
            resource_id=user.id,
            action="user.2fa_disabled",
            actor_user_id=user.id,
        )

    async def regenerate_backup_codes(self, user: User) -> list[str]:
        cred = await self.get_credential(user.id)
        if cred is None or not user.totp_enabled:
            raise TwoFactorError("two-factor authentication is not enabled")
        codes = generate_backup_codes()
        cred.backup_codes = [hash_backup_code(c) for c in codes]
        await self._session.commit()
        return codes

    def issue_challenge(self, user_id: str) -> str:
        """Short-lived token proving password auth passed; exchanged for tokens with a TOTP code."""
        token = secrets.token_urlsafe(32)
        _prune(_challenges, now_utc())
        _challenges[token] = (user_id, now_utc() + CHALLENGE_TTL)
        return token

    def consume_challenge(self, token: str) -> str:
        """Return the user_id for a valid challenge, single-use."""
        _prune(_challenges, now_utc())
        entry = _challenges.pop(token, None)
        if entry is None:
            raise TwoFactorError("challenge expired or invalid")
        return entry[0]

    async def verify_login_code(self, user: User, *, code: str) -> bool:
        """Verify a TOTP code or backup code. Backup codes are single-use."""
        cred = await self.get_credential(user.id)
        if cred is None or not user.totp_enabled:
            raise TwoFactorError("two-factor authentication is not enabled")
        secret = secret_from_base32(self._cipher.decrypt(cred.secret_ciphertext))
        counter = verify(secret, code, last_counter=cred.last_counter)
        if counter is not None:
            cred.last_counter = counter
            await self._session.commit()
            return True
        digest = hash_backup_code(code)
        if digest in (cred.backup_codes or []):
            cred.backup_codes = [h for h in cred.backup_codes if h != digest]
            await self._session.commit()
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user.id,
                action="user.2fa_backup_code_used",
                actor_user_id=user.id,
            )
            return True
        return False

    async def list_sessions(self, user_id: str) -> list[RefreshToken]:
        stmt = (
            select(RefreshToken)
            .where(RefreshToken.user_id == user_id)
            .order_by(RefreshToken.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
