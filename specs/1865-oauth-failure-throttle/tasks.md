# Tasks: rate-limit failed OAuth callbacks (#1865)

## Phase 1 — Setup and tests first

- [ ] T001 [AC-6] apps/api/tests/test_oauth.py — update `test_oauth_callback_account_gone_redirects` expectation: with budget of 1, first vanished-account attempt is 302, second is 429 (replaces the old "neither attempt may trip a 429" assertion).
- [ ] T002 [P] [AC-1, AC-2] apps/api/tests/test_oauth.py — add failing-callbacks-throttled test: tiny budget, repeat invalid-state callbacks from one address/provider, assert eventual 429 with `Retry-After` header; in-budget attempts still 302.
- [ ] T003 [P] [AC-3] apps/api/tests/test_oauth.py — add success-leaves-budget test: partial budget consumed by failures, one successful callback via `_mock_oauth`/`_callback`, assert remaining budget unchanged (direct sign-in and 2FA-park cases).
- [ ] T004 [P] [AC-4] apps/api/tests/test_oauth.py — add isolation test: exhausted key for one address/provider does not 429 a different address or provider.
- [ ] T005 [AC-1] apps/api/tests/test_oauth.py — run T001–T004 against unmodified code, confirm the new expectations fail (302 where 429 expected).

## Phase 2 — Implementation

- [ ] T006 [AC-1, AC-2] apps/api/src/api/routes/oauth.py — in `oauth_callback`, bind the `oauth:<ip>:<provider>` key once, keep `check(key)`, add `fail(key)` before each of the 7 `_error_redirect` failure returns; leave both success returns uncharged.
- [ ] T007 [AC-5] apps/api/src/core/security/ratelimit.py — rewrite the module-docstring OAuth sentence: failed callbacks are charged, successes (incl. 2FA park) are not.
- [ ] T008 [AC-5] apps/api/src/api/routes/oauth.py — update the stale "bucket this module never charges" comment at the callback `check` to describe the failure charge.

## Phase 3 — Polish

- [ ] T009 [AC-6] apps/api/tests/test_oauth.py — re-run full `test_oauth.py` plus `test_login_rate_limit.py` (no regressions in adjacent limiter behavior); verify tests fail with the `fail` calls removed and pass with them present.
- [ ] T010 [polish] repo — smoke test: `cd apps/api && uv run --extra dev pytest tests/test_oauth.py -q`.
- [ ] T011 [polish] repo — quality gate from `Makefile`: `make api-test` and `make api-lint`.
