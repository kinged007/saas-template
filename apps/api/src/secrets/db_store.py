"""DB-backed SecretStore: version-encrypted rows in the `stored_secrets` table.

This is the reference implementation behind the `SecretStore` interface. A
secret-vault adapter can replace it later (same interface, different
backend) without touching the worker or the API.

Each value is encrypted with `SecretCipher` into a versioned Fernet envelope
(`vN.<token>`); the version is stored alongside so a future vault migration
or key rotation can re-encrypt selectively. The plaintext never touches the
database or the ORM layer.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from src.core.security.crypto import SecretCipher
from src.models.secret import StoredSecret
from src.secrets.base import SecretRecord, SecretStore


def _parse_version(ciphertext: str) -> int:
    """Extract the envelope version (`vN.<token>`) or 1 for legacy tokens."""
    try:
        version_raw = ciphertext.split(".", 1)[0]
        if version_raw.startswith("v"):
            return int(version_raw[1:])
    except (ValueError, IndexError):
        pass
    return 1


class DbSecretStore(SecretStore):
    def __init__(self, session_factory, cipher: SecretCipher) -> None:
        self._session_factory = session_factory
        self._cipher = cipher

    async def put(
        self,
        *,
        workspace_id: str,
        key: str,
        value: str,
        kind: str,
        label: str | None = None,
        key_id: str | None = None,
        meta: dict | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        ciphertext = self._cipher.encrypt(value)
        version = _parse_version(ciphertext)
        stored_meta = dict(meta or {})
        if key_id:
            stored_meta["key_id"] = key_id
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(StoredSecret).where(
                        StoredSecret.workspace_id == workspace_id,
                        StoredSecret.secret_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = StoredSecret(
                    workspace_id=workspace_id,
                    secret_key=key,
                    kind=kind,
                    label=label,
                    ciphertext=ciphertext,
                    key_version=version,
                    meta=stored_meta,
                    expires_at=expires_at,
                )
                session.add(row)
            else:
                row.kind = kind
                row.label = label
                row.ciphertext = ciphertext
                row.key_version = version
                row.meta = stored_meta
                row.expires_at = expires_at
            await session.commit()

    async def get(self, *, workspace_id: str, key: str) -> SecretRecord | None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(StoredSecret).where(
                        StoredSecret.workspace_id == workspace_id,
                        StoredSecret.secret_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            return _to_record(row, self._cipher.decrypt(row.ciphertext))

    async def delete(self, *, workspace_id: str, key: str) -> None:
        async with self._session_factory() as session:
            row = (
                await session.execute(
                    select(StoredSecret).where(
                        StoredSecret.workspace_id == workspace_id,
                        StoredSecret.secret_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                await session.delete(row)
                await session.commit()

    async def list_for_workspace(
        self, workspace_id: str, *, prefix: str | None = None
    ) -> list[SecretRecord]:
        stmt = select(StoredSecret).where(StoredSecret.workspace_id == workspace_id)
        if prefix:
            stmt = stmt.where(StoredSecret.secret_key.like(f"{prefix}%"))
        stmt = stmt.order_by(StoredSecret.created_at.asc())
        async with self._session_factory() as session:
            rows = (await session.execute(stmt)).scalars().all()
            return [_to_record(row, self._cipher.decrypt(row.ciphertext)) for row in rows]


def _to_record(row: StoredSecret, value: str) -> SecretRecord:
    return SecretRecord(
        key=row.secret_key,
        kind=row.kind,
        label=row.label,
        value=value,
        key_id=(row.meta or {}).get("key_id"),
        meta=row.meta or {},
        created_at=row.created_at,
        expires_at=row.expires_at,
    )
