"""In-memory sliding-window rate limiter for auth endpoints.

Deliberately dependency-free (no slowapi/redis): a locked dict of per-key
failure timestamps. Single-process only.

`fail(key)` marks a request that did not authenticate, so a 401 on a throttled
entry point is no proof that its key was charged. Branches leave the budget
intact for two unrelated reasons:

- On purpose, because the credentials were accepted and the caller is not
  finished: the 2FA challenge on POST /auth/login.
- Because that branch never charges: /auth/2fa/login's 401s raised before
  `check` (challenge-token guessing is unthrottled by this limiter) and by
  `verify_login_code`, where only a rejected code charges, on `ip:<user_id>`
  rather than on login's `ip:<email>`, and `auth.py`'s account-disabled 401
  after `check`. Every OAuth route likewise calls `check`
  and no `fail`.

`check` consults two keys on POST /auth/login: the (IP, email) key and the
account key (`account:<email>`), so distributed guessing against one inbox
from many addresses shares one budget. Exhausting the window budget locks the
key for `lockout_seconds` (0 disables, pure sliding window); a success
`reset`s both keys.

Locking the account key can lock the real owner out; intentional
brute-force vs. availability tradeoff.

Read the route, not this list, before adding a `fail`.
# ponytail: ceiling is one replica; move to Redis when the API scales out.
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
        lockout_seconds: int = 900,
        max_keys: int = 10_000,
    ) -> None:
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self.max_keys = max_keys
        self._failures: dict[str, deque[float]] = {}
        self._locked_until: dict[str, float] = {}
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
        """Raise 429 when the key has exhausted its failure budget.

        A key that just exhausted the window is locked for `lockout_seconds`
        (0 disables the lock, the Retry-After falls back to the window); a
        locked key stays 429 until the lockout lapses, which also clears the
        window history accumulated beneath it.
        """
        now = time.monotonic()
        with self._lock:
            locked_until = self._locked_until.get(key)
            if locked_until is not None:
                if locked_until > now:
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        "too many attempts, try again later",
                        headers={"Retry-After": str(int(locked_until - now) + 1)},
                    )
                del self._locked_until[key]
                self._failures.pop(key, None)
            hits = self._prune(key, now)
            if hits is not None and len(hits) >= self.max_attempts:
                if self.lockout_seconds > 0:
                    self._locked_until[key] = now + self.lockout_seconds
                    retry_after = self.lockout_seconds
                else:
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
                    evicted = next(iter(self._failures))
                    self._failures.pop(evicted)
                    self._locked_until.pop(evicted, None)
                hits = self._failures[key] = deque()
            hits.append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
            self._locked_until.pop(key, None)

    def clear(self) -> None:
        """Drop every key (tests reset the limiter between tests)."""
        with self._lock:
            self._failures.clear()
            self._locked_until.clear()


auth_limiter = SlidingWindowLimiter()


def get_auth_limiter() -> SlidingWindowLimiter:
    """Limiter honoring settings (tests override settings before first use).

    Note: replacing the global drops all failure state when settings differ.
    Harmless in production (settings are static); tests that monkeypatch
    settings silently reset limiter state.
    """
    from src.settings import settings

    global auth_limiter
    wanted = (
        settings.auth_rate_limit_max_attempts,
        settings.auth_rate_limit_window_seconds,
        settings.auth_rate_limit_lockout_seconds,
    )
    current = (
        auth_limiter.max_attempts,
        auth_limiter.window_seconds,
        auth_limiter.lockout_seconds,
    )
    if wanted != current:
        auth_limiter = SlidingWindowLimiter(
            max_attempts=wanted[0], window_seconds=wanted[1], lockout_seconds=wanted[2]
        )
    return auth_limiter


register_limiter = SlidingWindowLimiter()


def get_register_limiter() -> SlidingWindowLimiter:
    """Per-IP cap on POST /auth/register (#1343): a separate instance and key
    space (IP alone, never the login account:<email> key), with its own
    settings pair so tightening the auth brute-force budget
    in a test cannot strangle this window (register_user is universal setup).

    The registrant owns every fresh address, so per-(IP, email) keying cannot
    bound the verification mail it sends — the key is the IP alone. The separate
    instance keeps that window out of login/forgot/resend's (IP, email) budget
    and vice versa; conftest clears it per test so the universal `register_user`
    setup path is never throttled by another test's spend.
    Shares only the auth lockout-duration setting.
    """
    from src.settings import settings

    global register_limiter
    wanted = (
        settings.auth_register_rate_limit_max_attempts,
        settings.auth_register_rate_limit_window_seconds,
        settings.auth_rate_limit_lockout_seconds,
    )
    current = (
        register_limiter.max_attempts,
        register_limiter.window_seconds,
        register_limiter.lockout_seconds,
    )
    if wanted != current:
        register_limiter = SlidingWindowLimiter(
            max_attempts=wanted[0], window_seconds=wanted[1], lockout_seconds=wanted[2]
        )
    return register_limiter
