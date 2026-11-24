# Plan: Nonce and browser-bound state cookie for SSO flow (#1864)

Spec: `specs/1864-sso-nonce-state-cookie/spec.md` (Status: Clarified).
Area context was missing (no `area:<name>` label on the issue, no `.agents/areas/` directory in the repo); the plan is grounded in the repo docs (`AGENTS.md`, `Makefile`, `.github/workflows/ci.yml`) and the confirmed code paths below.

## Approach

Reuse the existing single-use server-side state entry as the anchor for both values, following the patterns already in the codebase:

1. **Nonce**: `build_authorize_url` in `apps/api/src/services/oauth.py` already mints `state` and the PKCE verifier and stores `{provider, redirect_uri, code_verifier}` under `STATE_TTL_HINT + state`. Add a fresh `secrets.token_urlsafe` nonce to that entry and to the provider redirect as a `nonce` query param. At callback, `claims_from_id_token` (same file) compares the ID token's `nonce` claim against the entry's nonce and returns `None` on missing/mismatch, which the callback already turns into the standard login-error redirect with no session, token, or account change. Nonce verification applies only when an ID token is returned (pure-OAuth2 providers skip it); the cookie check always applies.
2. **`oauth_state` cookie**: the authorize route sets a short-lived, single-use, HttpOnly cookie whose flags reuse `cookie_secure_for(request)` per-request Secure derivation and `SameSite=Lax` from `apps/api/src/core/security/cookies.py` (per the spec clarification, same conventions as the session cookies, so plain-HTTP local dev keeps working). The value is bound to the state entry (stored alongside it); the callback rejects a missing or non-matching cookie via the existing `_error_redirect("invalid or expired state")` path before any token exchange or user upsert. Consumption stays single-use through the existing `consume_state` delete, so replays fail.

Why this shape: no new store, no migration, no new dependency, no new error surface — both checks funnel into the two rejection paths the callback already has (`invalid or expired state` before exchange, `sign-in failed` after a refused ID token), which already create nothing and redirect to the standard login-error outcome.

## Files to change

- `apps/api/src/services/oauth.py` — `build_authorize_url`: mint nonce, persist in state entry, append `nonce` to authorize params; `claims_from_id_token`: accept the expected nonce and return `None` when the token nonce is missing or mismatched.
- `apps/api/src/api/routes/oauth.py` — `oauth_authorize`: set the `oauth_state` cookie on the 302 response; `oauth_callback`: compare request cookie against the consumed state entry before `exchange_code`, rejecting via `_error_redirect` on missing/mismatch.
- `apps/api/src/core/security/cookies.py` — only if a small `set_oauth_state_cookie`-style helper is needed to keep flag logic in the single place the module docstring mandates; otherwise reuse `cookie_secure_for` inline. No flag reinvention in the route.
- `apps/api/tests/test_oauth.py` — new rejection tests per AC plus happy-path/2FA coverage; extend the existing `_callback` helper to seed nonce + cookie the way `/authorize` will.

All paths above were confirmed with `grep`/`read` (route and service line numbers cited in the task list context). No function or file is named that was not confirmed.

## Data and contract changes

- HTTP contract: `GET /auth/oauth/{provider}/authorize` 302 gains a `nonce` query param on the provider URL and an `oauth_state` `Set-Cookie`; `GET .../callback` behavior is unchanged except the two new rejection cases, both surfacing as the existing `/login?error=` redirect. No new status codes or pages.
- Server-side state cache entry (`STATE_TTL_HINT + state`): gains nonce and cookie-binding fields; same TTL, same single-use delete. Ephemeral only.
- Internal signature: `claims_from_id_token` gains an expected-nonce input. No DB migration, no new env var, no new dependency, no frontend change.

## Test plan

Tests first, in `apps/api/tests/test_oauth.py` (existing `_mock_oauth`/`_callback` patterns; refused-token precedent is `test_callback_refused_id_token_fails_login`):

- AC-2: callback with ID token lacking `nonce` → 302 to `/login?error=`, user count unchanged.
- AC-3: callback with ID token carrying a different nonce → same rejection.
- AC-4: callback without the `oauth_state` cookie → same rejection.
- AC-5: callback with a non-matching cookie value → same rejection.
- AC-6: fully matching attempt completes login exactly as before (standard user + `totp_enabled` 2FA branch asserting the one-time-code redirect).
- AC-7: replay of consumed parameters (same state twice / cross-attempt values) rejected.
- Smoke test: `cd apps/api && uv run pytest tests/test_oauth.py -q --tb=short -p no:cacheprovider` (subset run of the real app via the existing test client; the authorize-redirect test exercises the live 302 including the new param and cookie).

## Risks

- `risk:high` is on the issue: the callback is the login front door. Mitigation is fail-closed checks placed before `exchange_code`/`upsert_oauth_user`, plus user-count assertions in every rejection test.
- Cookie `Secure` on plain-HTTP dev/proxy setups: mitigated by reusing `cookie_secure_for(request)` instead of a hardcoded flag.
- Two concurrent attempts and double-callback replays: values are per attempt and single-use; covered by AC-7 tests.
- The description cites "the reference implementation from PR #39", but PR #39 in this repository is closed as "account linking on the existing OAuth service" and contains no nonce implementation; the plan assumes a fresh implementation following the existing `oauth.py`/`cookies.py` patterns (see open question in the handoff comment).

## Rollback

Revert the implementing commits. Safe without a data migration: the only persisted shape is the ephemeral TTL cache entry, which expires on its own; old entries without the new fields fail closed (rejected as invalid state) rather than half-accepted. No frontend or config rollback needed.
