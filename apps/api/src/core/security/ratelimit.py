"""In-memory sliding-window rate limiter for auth endpoints.

Deliberately dependency-free (no slowapi/redis): a locked dict of per-key
failure timestamps. Single-process only.
# ponytail: ceiling is one replica; move to Redis when the API scales out.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, status


class SlidingWindowLimiter:
    def __init__(self, *, max_attempts: int = 10, window_seconds: int = 300) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        hits = self._failures.get(key)
        if hits is None:
            hits = self._failures[key] = deque()
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        return hits

    def check(self, key: str) -> None:
        """Raise 429 when the key has exhausted its failure budget."""
        now = time.monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if len(hits) >= self.max_attempts:
                retry_after = int(hits[0] + self.window_seconds - now) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "too many attempts, try again later",
                    headers={"Retry-After": str(retry_after)},
                )

    def fail(self, key: str) -> None:
        with self._lock:
            self._prune(key, time.monotonic()).append(time.monotonic())

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


auth_limiter = SlidingWindowLimiter()


def get_auth_limiter() -> SlidingWindowLimiter:
    """Limiter honoring settings (tests override settings before first use)."""
    from src.settings import settings

    global auth_limiter
    wanted = (settings.auth_rate_limit_max_attempts, settings.auth_rate_limit_window_seconds)
    current = (auth_limiter.max_attempts, auth_limiter.window_seconds)
    if wanted != current:
        auth_limiter = SlidingWindowLimiter(max_attempts=wanted[0], window_seconds=wanted[1])
    return auth_limiter
