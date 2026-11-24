# Plan: rate-limit failed OAuth callbacks (#1865)

Spec: `specs/1865-oauth-failure-throttle/spec.md` (Status: Draft; no `plan-check` revise verdict exists, so this is a fresh plan from the spec, not a revision).

## Approach

The callback (`oauth_callback` in `apps/api/src/api/routes/oauth.py`) currently
computes the per-address per-provider key `oauth:<ip>:<provider>`, calls
`check(key)`, and never calls `fail(key)` — the module docstring in
`ratelimit.py` even documents this ("Every OAuth route likewise calls `check`
and no `fail`"). Failures therefore never consume budget and `429` is
unreachable on this route.

The fix follows the existing `auth.py` login pattern (`check` at entry,
`fail` on each failure exit, nothing on success): bind the key once at the top
of `oauth_callback`, keep the existing `check(key)`, and call `fail(key)`
before each of the 7 failure exits that return `_error_redirect(...)`
(missing code/state; expired state x2 incl. provider mismatch; upstream
exchange/identity failure; registration-disabled; vanished-account join guard;
token-issue failure). The 2 success exits (direct token issue, second-factor
park at the `user.totp_enabled` branch) stay uncharged per FR-003. No timing,
budget-size, storage, or authorize/token-endpoint changes (out of scope).

Rule text: rewrite the `ratelimit.py` module docstring OAuth sentence to state
failed callbacks are charged and successes (including the 2FA park) are not,
and update the stale "never charges" comment above the callback's `check`.

Tests: the existing `test_oauth_callback_account_gone_redirects` (budget of 1,
two attempts, asserts no 429) locks in the old behavior and must be updated to
expect the second attempt throttled; new tests prove repeated failures from one
address/provider yield 429 with `Retry-After`, successes leave budget intact,
and budgets isolate per address/provider.

## Files to change

- `apps/api/src/api/routes/oauth.py` — in `oauth_callback`: bind
  `key = f"oauth:{_client_ip(request) or 'unknown'}:{provider_id}"` once;
  keep `check(key)`; add `get_auth_limiter().fail(key)` before each of the 7
  `_error_redirect(...)` returns (lines ~120, 124, 126, 160, 177, 188, 204);
  update the stale "never charges" comment at the `check` call. Success
  returns (2FA park, token issue) unchanged.
- `apps/api/src/core/security/ratelimit.py` — module docstring: replace the
  "Every OAuth route likewise calls `check` and no `fail`" sentence with a
  rule stating failed OAuth callbacks are charged (`fail` on every
  sign-in-failed redirect) and successful callbacks (including the 2FA park)
  are not.
- `apps/api/tests/test_oauth.py` — update
  `test_oauth_callback_account_gone_redirects` to the new behavior; add
  failure-charging tests (repeated invalid-state failures → 429 with
  retry hint; success-after-failures leaves budget; per-address/provider
  isolation).

## Data and contract changes

None. No schema, migration, config, env var, dependency, or public API shape
change. The only externally visible change is behavioral: exhausted failure
budgets now return the existing 429 shape (`too many attempts, try again
later` with `Retry-After` header, raised by `SlidingWindowLimiter.check`).

## Test plan

Tests first (before implementation, to confirm they fail on current code):

- T-a (AC-1/AC-2): tiny budget (`auth_rate_limit_max_attempts=1`), repeat a
  failing callback (invalid state) from one address → second attempt is 429
  with `Retry-After` header. Fails today (302, never 429).
- T-b (AC-3): consume part of the budget with failures, run one successful
  callback (`_mock_oauth` + `_callback` helper), show remaining budget
  unchanged (next failure counts as if the success never happened).
- T-c (AC-4): exhaust budget for address/provider A, show a different
  address or provider still gets the normal redirect.
- T-d (AC-6): the updated account-gone test plus T-a fail if the `fail`
  calls are removed, pass with them present.

Smoke test (smallest real run the repo documents): targeted backend run
`cd apps/api && uv run --extra dev pytest tests/test_oauth.py -q`
(scratch sqlite file, no docker required per `make api-test`).

Quality gate (from `Makefile`): `make api-test` (backend pytest) and
`make api-lint` (`ruff check` + `ruff format --check`). No frontend change,
so no web jobs.

## Risks

- Over-charging: charging a success path by mistake would lock legitimate SSO
  users out — mitigated by the explicit success-uncharged tests (AC-3) and by
  keeping the diff to `fail` calls on `_error_redirect` returns only.
- Under-charging: missing one of the 7 failure exits leaves a bypass —
  mitigated by enumerating all `_error_redirect` call sites and the AC-6
  removal test.
- Shared-budget surprise: the key is per address+provider, so a NAT-heavy
  address could throttle innocent users sharing the IP — accepted tradeoff,
  same semantics as the existing login limiter; budget sizes unchanged.
- `risk:high` label is auth-throttling sensitivity, not size: one route file
  plus rule text plus tests (`size:s`).

## Rollback

Revert the `oauth.py` `fail` calls and the docstring/comment text; restore the
old account-gone test expectation. No data migration, so rollback is a plain
`git revert` with no cleanup. Behavior after rollback: failed callbacks again
escape throttling (the bug returns, nothing else breaks).
