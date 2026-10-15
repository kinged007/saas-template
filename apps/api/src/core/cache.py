"""Tiny in-process TTL cache for provider responses."""

from __future__ import annotations

import asyncio
import copy
import threading
import time
from collections.abc import Awaitable, Callable
from functools import partial
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


class SingleFlight:
    """Coalesces concurrent async calls by key into one shared in-flight task.

    The first caller for a key runs the factory in a task; every caller arriving
    before it completes awaits the same task, so a burst on one key costs one
    execution and its outcome (value or exception) is shared by all joiners.
    The entry is dropped once the task is done, so a later caller starts fresh.
    A task from another loop (left behind by a closed pytest event loop) is
    replaced instead of awaited, since it can never complete on the new loop.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[Any]] = {}

    async def run(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        task = self._tasks.get(key)
        if task is not None and not task.done() and task.get_loop() is asyncio.get_running_loop():
            return await task
        task = asyncio.create_task(factory())
        self._tasks[key] = task
        task.add_done_callback(partial(self._discard, key))
        return await task

    def _discard(self, key: str, task: asyncio.Task[Any]) -> None:
        if self._tasks.get(key) is task:
            del self._tasks[key]
