"""Local-filesystem driver: files under STORAGE_DIR, keys are relative paths."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from src.storage.base import FileStorage, StorageError, StoredObject

logger = logging.getLogger(__name__)


def _resolve(root: Path, key: str) -> Path:
    # Keys are "<workspace_id>/<uuid>-<safe name>"; reject traversal.
    candidate = (root / key).resolve()
    if candidate != root and root not in candidate.parents:
        raise StorageError(f"invalid storage key: {key!r}")
    return candidate


class LocalFileStorage(FileStorage):
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).expanduser().resolve()

    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        dest = _resolve(self._root, key)
        try:
            await asyncio.to_thread(self._write, dest, content)
        except StorageError:
            raise
        except Exception as exc:
            raise StorageError(f"local put failed: {exc}") from exc

    def _write(self, dest: Path, content: bytes) -> None:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    async def get(self, *, key: str) -> StoredObject | None:
        try:
            dest = _resolve(self._root, key)
        except StorageError:
            # Fails closed like a missing key; log it so a rejected key is not
            # indistinguishable from an absent one.
            logger.warning("rejected storage key on read: %r", key)
            return None
        try:
            content = await asyncio.to_thread(dest.read_bytes)
        except FileNotFoundError:
            return None
        except Exception as exc:
            raise StorageError(f"local get failed: {exc}") from exc
        return StoredObject(key=key, content=content)

    async def delete(self, *, key: str) -> None:
        try:
            dest = _resolve(self._root, key)
        except StorageError:
            return
        await asyncio.to_thread(lambda: dest.unlink(missing_ok=True))
