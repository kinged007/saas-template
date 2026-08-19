"""Encrypted secret store entries.

Temporary storage for credential material that a provider only reveals ONCE
at creation time (e.g. Microsoft Graph's `addPassword` response carries the
plaintext `secretText`, but every later read returns `secretText: null`).
These are the values app developers need to point their applications at the
migrated apps.

Every payload is stored VERSION-ENCRYPTED at rest via `SecretCipher` (Fernet,
key chosen by `SECRET_ENCRYPT_VERSION`) — the raw secret never touches the
database. The store is behind the `SecretStore` interface so a dedicated
secret-vault adapter can replace the DB implementation without touching the
worker or the API.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class StoredSecret(Base, TimestampMixin):
    """One encrypted secret value, namespaced per workspace.

    `secret_key` is the caller-chosen logical id (e.g.
    `migration:<job_id>:<app_id>:password_secret:<key_id>`), unique per
    workspace. `ciphertext` is a versioned Fernet envelope (`vN.<token>`);
    `kind` describes the material (password_secret | client_secret | ...) so
    future vault adapters can route by type.
    """

    __tablename__ = "stored_secrets"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    secret_key: Mapped[str] = mapped_column(String(400), index=True, nullable=False)
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    label: Mapped[str | None] = mapped_column(String(300), nullable=True)
    # versioned Fernet envelope: "v<version>.<token>" (see SecretCipher)
    ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, nullable=False)
    meta: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
