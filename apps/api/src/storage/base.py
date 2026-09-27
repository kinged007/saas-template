"""File storage contract: binary-object backend behind one interface.

Drivers: local filesystem (dev default) and S3-compatible HTTP (prod).
Selected via STORAGE_DRIVER; callers only depend on FileStorage (see factory).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class StorageDriver(StrEnum):
    LOCAL = "local"
    S3 = "s3"


class StorageError(RuntimeError):
    """Raised when a driver cannot store or fetch an object."""


@dataclass
class StoredObject:
    key: str
    content: bytes


class FileStorage(ABC):
    """Interface for storing and fetching binary objects by key."""

    name = "base"

    @abstractmethod
    async def put(self, *, key: str, content: bytes, content_type: str | None = None) -> None:
        """Store `content` under `key` (overwrite). Raises StorageError."""

    @abstractmethod
    async def get(self, *, key: str) -> StoredObject | None:
        """Fetch one object; None when the key does not exist."""

    @abstractmethod
    async def delete(self, *, key: str) -> None:
        """Remove one object; missing keys are a no-op."""

    async def aclose(self) -> None:
        """Release driver-held resources. No-op unless the driver holds any."""
        return None
