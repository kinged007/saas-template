"""Tiny in-process TTL cache for provider responses."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any


class TtlCache:
    """Thread-safe, in-memory cache with per-entry absolute expiry.

    Entries expire `ttl_seconds` after being written and are dropped lazily on
    read. Values are returned as deep copies so callers can never corrupt the
    cached payload. Single-process only — the API layer is the only caller of
    provider endpoints, so no shared/Redis backend is needed.
    """

    def __init__(self, ttl_seconds: float = 300.0) -> None:
        self._ttl = ttl_seconds
        self._store: dict[str, tuple[float, Any]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expires_at, value = entry
            if time.monotonic() > expires_at:
                del self._store[key]
                return None
            return copy.deepcopy(value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def set(self, key: str, value: Any) -> None:
        with self._lock:
            self._store[key] = (time.monotonic() + self._ttl, value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
