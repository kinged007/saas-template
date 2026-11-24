# Tasks: Nonce and browser-bound state cookie for SSO flow (#1864)

## Phase 1 — Setup and tests first

- [ ] T001 [AC-2, AC-3] apps/api/tests/test_oauth.py — add failing callback tests for ID token with missing nonce and with mismatched nonce (assert 302 to `/login?error=` and unchanged user count).
- [ ] T002 [AC-4, AC-5] apps/api/tests/test_oauth.py — add failing callback tests for missing `oauth_state` cookie and non-matching cookie value (same rejection assertions; extend `_callback` helper to seed nonce + cookie like `/authorize` will).
- [ ] T003 [AC-6, AC-7] apps/api/tests/test_oauth.py — add failing happy-path tests: fully matching attempt completes login (standard user and `totp_enabled` 2FA one-time-code branch) and consumed/cross-attempt parameters are rejected on replay.

## Phase 2 — Implementation

- [ ] T004 [AC-1] apps/api/src/services/oauth.py — in `build_authorize_url`, mint a fresh nonce per attempt, persist it in the `STATE_TTL_HINT` entry, and append it as the `nonce` authorize param.
- [ ] T005 [AC-2, AC-3] apps/api/src/services/oauth.py — in `claims_from_id_token`, verify the ID token `nonce` against the attempt's nonce and return `None` on missing/mismatch (applies only when an ID token is returned).
- [ ] T006 [AC-1, AC-4, AC-5] apps/api/src/api/routes/oauth.py (+ apps/api/src/core/security/cookies.py only for a shared flag helper if needed) — set the short-lived single-use `oauth_state` cookie in `oauth_authorize` (HttpOnly, per-request Secure via `cookie_secure_for`, SameSite=Lax); in `oauth_callback`, reject missing/non-matching cookie via `_error_redirect` before any token exchange or user upsert.
- [ ] T007 [AC-6, AC-7] apps/api/src/api/routes/oauth.py — wire the stored nonce and cookie binding through `consume_state` into the callback checks so matching attempts complete unchanged (including the 2FA branch) and consumed entries reject replays.

## Phase 3 — Polish

- [ ] T008 [AC-8] apps/api/tests/test_oauth.py — confirm one test per rejection in AC-2 through AC-5 plus the AC-6 happy path exists and the full file passes.
- [ ] T009 [polish] repo root — run the quality gate (`make api-test`, `make api-lint`; CI runs `uv run ruff check .`, `ruff format --check .`, `uv run pytest -q --tb=short -p no:cacheprovider` per `.github/workflows/ci.yml`) and the smoke test (`uv run pytest tests/test_oauth.py -q --tb=short -p no:cacheprovider` from `apps/api`, covering the live authorize 302 with nonce param and cookie).
