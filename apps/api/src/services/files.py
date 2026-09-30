"""File upload orchestration: validate → store bytes → persist metadata."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.prefix import API
from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.file_object import FileObject
from src.models.workspace import WorkspaceMember
from src.settings import settings
from src.storage.base import FileStorage, StorageError

logger = logging.getLogger(__name__)

ALLOWED_AVATAR_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
# The /files route stores more than avatars eventually; each purpose names the
# (content types, extensions) it accepts.
# ponytail: purpose is validated but not stored on the row — add a column when a
# second purpose needs to be listed or filtered on.
_PURPOSES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "avatar": (frozenset(ALLOWED_AVATAR_TYPES), frozenset(ALLOWED_EXTENSIONS)),
}
_FILENAME_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class FileError(Exception):
    pass


class FileForbidden(FileError):
    pass


class FileNotFound(FileError):
    pass


class FileTooLarge(FileError):
    pass


class FileTypeRejected(FileError):
    pass


def _safe_filename(name: str) -> str:
    base = (name or "upload").rsplit("/", 1)[-1].rsplit("\\", 1)[-1].strip() or "upload"
    return _FILENAME_SAFE.sub("_", base)[:200]


async def purge_objects(storage: FileStorage | None, keys: Sequence[str]) -> None:
    """Drop the stored bytes behind rows that are being deleted.

    Best-effort by design: a storage failure must not fail an account or
    workspace deletion, so every error is logged and the sweep continues.
    """
    if not keys:
        return
    if storage is None:
        logger.warning("no storage driver configured; %d stored objects orphaned", len(keys))
        return
    for key in keys:
        try:
            await storage.delete(key=key)
        except Exception:
            logger.exception("failed to delete stored object %s", key)


class FileService:
    def __init__(
        self,
        session: AsyncSession,
        storage: FileStorage,
        max_upload_bytes: int,
        bus: EventBus | None = None,
    ) -> None:
        self._session = session
        self._storage = storage
        self._max_bytes = max_upload_bytes
        self._bus = bus

    async def _ensure_membership(self, workspace_id: str, user_id: str) -> None:
        result = await self._session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.status == "active",
            )
        )
        if result.scalar_one_or_none() is None:
            raise FileForbidden("you are not a member of this workspace")

    @staticmethod
    def to_dict(row: FileObject) -> dict:
        return {
            "id": row.id,
            "workspace_id": row.workspace_id,
            "owner_user_id": row.owner_user_id,
            "filename": row.filename,
            "content_type": row.content_type,
            "size_bytes": row.size_bytes,
            # Absolute so a browser can load it whatever origin serves the UI.
            "url": f"{settings.frontend_url.rstrip('/')}{API}/files/{row.id}",
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }

    async def upload(
        self,
        *,
        workspace_id: str,
        owner_user_id: str,
        filename: str,
        content_type: str | None,
        content: bytes,
        ip_address: str | None = None,
        purpose: str = "avatar",
    ) -> dict:
        await self._ensure_membership(workspace_id, owner_user_id)
        allowed = _PURPOSES.get(purpose)
        if allowed is None:
            raise FileError(f"unknown purpose: {purpose}")
        allowed_types, allowed_extensions = allowed
        mime = (content_type or "").split(";")[0].strip().lower()
        if mime not in allowed_types:
            raise FileTypeRejected(f"unsupported content type: {content_type or 'unknown'}")
        ext = Path(_safe_filename(filename)).suffix.lower()
        if ext not in allowed_extensions:
            raise FileTypeRejected(f"unsupported file extension: {ext or 'none'}")
        if len(content) > self._max_bytes:
            raise FileTooLarge(f"file exceeds {self._max_bytes} bytes")
        if not content:
            raise FileError("empty file")
        safe = _safe_filename(filename)
        key = f"{workspace_id}/{uuid.uuid4()}-{safe}"
        try:
            await self._storage.put(key=key, content=content, content_type=mime)
        except StorageError as exc:
            raise FileError(str(exc)) from exc
        row = FileObject(
            workspace_id=workspace_id,
            owner_user_id=owner_user_id,
            filename=safe,
            content_type=mime,
            size_bytes=len(content),
            storage_key=key,
        )
        self._session.add(row)
        try:
            await self._session.commit()
        except Exception:
            # Row insert failed (e.g. transient DB error): remove the
            # orphaned bytes so storage never holds unreferenced objects.
            await self._storage.delete(key=key)
            raise
        await self._session.refresh(row)
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="file",
            resource_id=row.id,
            action="file.uploaded",
            actor_user_id=owner_user_id,
            details={"filename": safe, "size_bytes": len(content)},
            ip_address=ip_address,
        )
        return self.to_dict(row)

    async def download(
        self, *, workspace_id: str, file_id: str, user_id: str, ip_address: str | None = None
    ) -> tuple[FileObject, bytes]:
        await self._ensure_membership(workspace_id, user_id)
        row = await self._session.get(FileObject, file_id)
        if row is None or row.workspace_id != workspace_id:
            raise FileNotFound("file not found")
        try:
            stored = await self._storage.get(key=row.storage_key)
        except StorageError as exc:
            raise FileError(str(exc)) from exc
        if stored is None:
            raise FileNotFound("file not found")
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="file",
            resource_id=row.id,
            action="file.downloaded",
            actor_user_id=user_id,
            details={"filename": row.filename, "size_bytes": row.size_bytes},
            ip_address=ip_address,
        )
        return row, stored.content

    async def list_files(
        self, *, workspace_id: str, user_id: str, offset: int = 0, limit: int = 20
    ) -> tuple[list[dict], int]:
        await self._ensure_membership(workspace_id, user_id)
        total = (
            await self._session.execute(
                select(func.count())
                .select_from(FileObject)
                .where(FileObject.workspace_id == workspace_id)
            )
        ).scalar_one()
        rows = (
            (
                await self._session.execute(
                    select(FileObject)
                    .where(FileObject.workspace_id == workspace_id)
                    .order_by(FileObject.created_at.desc())
                    .offset(offset)
                    .limit(limit)
                )
            )
            .scalars()
            .all()
        )
        return [self.to_dict(r) for r in rows], int(total)
