from __future__ import annotations

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt

from src.settings import settings

logger = logging.getLogger(__name__)

ALGORITHM = "HS256"


def create_access_token(user_id: str, *, expires_minutes: int | None = None) -> str:
    expires = datetime.now(UTC) + timedelta(
        minutes=expires_minutes or settings.access_token_expire_minutes
    )
    return jwt.encode(
        {"sub": user_id, "type": "access", "exp": expires, "iat": datetime.now(UTC)},
        settings.secret_key,
        algorithm=ALGORITHM,
    )


def decode_access_token(token: str) -> dict[str, Any]:
    return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])


class OpaqueToken:
    """Opaque (DB-backed) token with hashed storage — used for refresh tokens."""

    @staticmethod
    def generate() -> str:
        return secrets.token_urlsafe(48)

    @staticmethod
    def hash(raw: str) -> str:
        import hashlib

        return hashlib.sha256(raw.encode("utf-8")).hexdigest()
