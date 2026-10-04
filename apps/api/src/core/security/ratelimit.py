"""In-memory sliding-window rate limiter for auth endpoints.

Deliberately dependency-free (no slowapi/redis): a locked dict of per-key
failure timestamps. Single-process only.
# ponytail: ceiling is one replica; move to Redis when the API scales out.

`fail(key)` marks a request that did not authenticate, so not every 401 on a
throttled entry point calls it: a 401 that asks the caller for more — the 2FA
challenge on POST /auth/login, the OAuth callback's error redirect for an
account that is gone — means the credentials were accepted, and charging it
would spend the caller's budget on a sign-in that has not failed yet.
"""

from __future__ import annotations

import threading
import time
from collections import deque

from fastapi import HTTPException, status


class SlidingWindowLimiter:
    def __init__(
        self,
        *,
        max_attempts: int = 10,
        window_seconds: int = 300,
        max_keys: int = 10_000,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float] | None:
        hits = self._failures.get(key)
        if hits is None:
            return None
        cutoff = now - self.window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._failures[key]
            return None
        return hits

    def check(self, key: str) -> None:
        """Raise 429 when the key has exhausted its failure budget."""
        now = time.monotonic()
        with self._lock:
            hits = self._prune(key, now)
            if hits is not None and len(hits) >= self.max_attempts:
                retry_after = int(hits[0] + self.window_seconds - now) + 1
                raise HTTPException(
                    status.HTTP_429_TOO_MANY_REQUESTS,
                    "too many attempts, try again later",
                    headers={"Retry-After": str(retry_after)},
                )

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            hits = self._prune(key, now)
            if hits is None:
                if len(self._failures) >= self.max_keys:
                    self._failures.pop(next(iter(self._failures)))
                hits = self._failures[key] = deque()
            hits.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)


auth_limiter = SlidingWindowLimiter()


def get_auth_limiter() -> SlidingWindowLimiter:
    """Limiter honoring settings (tests override settings before first use).

    Note: replacing the global drops all failure state when settings differ.
    Harmless in production (settings are static); tests that monkeypatch
    settings silently reset limiter state.
    """
    from src.settings import settings

    global auth_limiter
    wanted = (settings.auth_rate_limit_max_attempts, settings.auth_rate_limit_window_seconds)
    current = (auth_limiter.max_attempts, auth_limiter.window_seconds)
    if wanted != current:
        auth_limiter = SlidingWindowLimiter(max_attempts=wanted[0], window_seconds=wanted[1])
    return auth_limiter
