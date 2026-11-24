# Plan: #1807 — OAuth callback latch spec fails 3 runs running (wrong count of token exchanges)

Source: `specs/1807-oauth-latch-retry/spec.md` (present; requirements below trace to it, plus issue #1807 description and the spec-stage comment).

## Approach

The failing assertion is `apps/web/e2e/oauth-callback.spec.ts:116` (`expect(tokenPosts).toHaveLength(2)` receiving 1) in the spec `"a failed exchange drops its latch, so a repeat visit retries"`. Two candidate causes are still open, and the issue forbids assuming the latch is at fault — so the implement stage **diagnoses first, then fixes one branch**:

1. **Diagnose (cheap, decisive):** re-run the single spec with the back/forward cache disabled for the second visit (CDP `Page.setBFCacheEnabled(false)`, or log whether the callback mount effect re-ran on the return visit). If two POSTs appear with bfcache off, the cause is a bfcache restore of `/oauth/callback` on `page.goBack()` — the JS never re-ran, so one POST plus an already-rendered failure state is exactly what a correct latch also produces.
2. **Branch A — bfcache (spec-only fix):** replace the `Back to sign-in` click + `page.goBack()` round trip with a real client-side navigation that is not restorable (an in-app link back into `/oauth/callback?code=code-123`), keep the two-POST assertion, and leave a one-line comment saying why `goBack()` is not used. This matches the existing `navigate(..., { replace: true })` intent in `OAuthCallbackPage`, which already tries to keep the consumed code URL out of history.
3. **Branch B — latch (product fix):** the `.catch` in `OAuthCallbackPage` (`apps/web/src/components/AuthConfig.tsx`, ~line 135) clears `consumedCode` and then calls `setStatus` on a component that may already be torn down (user clicked away before rejection landed), or a second mount reads the guard before the clear lands. Fix so the release holds whether or not the view is still mounted. To satisfy AC-6 with the repo's stdlib-only `node --test` setup (no `.tsx`, no `@/` alias — see AGENTS.md), move the latch read/write/clear into the plain framework-free module `apps/web/src/components/oauth-callback.ts` next to `oauthCodeConsumed`, and cover release-after-teardown there with `node:test`.

Why this shape: the smallest change that restores a trustworthy signal. One branch is spec-only; the other touches one component plus its already-existing plain-module test file. No backend, timeout, success-path, or missing-code changes (all out of scope per spec).

## Files to change

- `apps/web/e2e/oauth-callback.spec.ts` — Branch A: replace the `goBack()` round trip with a non-restorable in-app re-navigation + one comment explaining why `goBack()` is not used (AC-3, AC-4). Branch B: unchanged navigation (it is the user path). Either way: keep the two-POST assertion, no skip/`fixme` (spec FR-004/FR-005).
- `apps/web/src/components/AuthConfig.tsx` — Branch B only: make the failed-exchange latch release mount-independent (AC-1, AC-2, FR-001). Success-path latch and all other branches unchanged.
- `apps/web/src/components/oauth-callback.test.ts` — Branch B only: add the clear-on-unmount/release-after-teardown case (AC-6). If the latch moves into `oauth-callback.ts` for testability, that file gains the small latch unit; its public helpers (`oauthCodeConsumed`, `oauthCallbackLoginHref`, `OAUTH_CALLBACK_TIMEOUT_MS`) keep their signatures.
- `apps/web/src/components/oauth-callback.ts` — Branch B only, only if the latch unit moves here for testability (see above).

## Data and contract changes

None. No public interfaces, schemas, persisted data, config, or dependencies change. The token endpoint, its error responses, and the success-path guard are untouched.

## Test plan

- **Diagnose first:** single-spec run with bfcache disabled (or a mount-effect log) to pick Branch A vs B before editing product code.
- **Branch A:** the updated e2e spec itself is the test (AC-1: two POSTs; AC-2: failure message visible, pending indicator absent; AC-4: assertion active + explanatory comment).
- **Branch B:** new `node:test` case in `oauth-callback.test.ts` covering release when the view is gone (AC-6), run via `make web-test` (repo: `node --test "src/**/*.test.ts"` in `apps/web`); the existing e2e spec covers AC-1/AC-2 unchanged.
- **Smoke test:** `npx playwright test e2e/oauth-callback.spec.ts` in `apps/web` (targeted single-file run, fastest real run of the changed artifact).
- **Acceptance gate (AC-5):** three consecutive full runs — `make web-test-e2e` locally (`cd apps/web && npm run test:e2e`) or the `e2e` CI workflow (`.github/workflows/e2e.yml`) on the branch; all three must pass.
- **Quality gate:** `make web-build` (tsc --noEmit + vite build), `make web-test` (both per root `AGENTS.md` and `Makefile`); e2e via `make web-test-e2e` / CI `e2e` workflow.

## Risks

- **Wrong-branch fix (high):** assuming the latch is broken and editing auth-path code when the cause is bfcache — or vice versa. Mitigated by the diagnose-first step; the bfcache-disabled run separates them cleanly.
- **Auth-path regression (high):** a wrong clear/guard change turns a failed exchange into a silent hang with no error and no escape. Mitigated by keeping the two-POST assertion enforced and the success-path latch unchanged; `risk:high` label stays.
- **Flaky acceptance (medium):** three full e2e runs are slow and the suite may flake elsewhere; AC-5 needs all-green runs, so unrelated flakes must be distinguished from this spec (169/170 pass baseline from the issue).
- **Untestable latch placement (low):** `AuthConfig.tsx` cannot load under `node --test` (React/`@/` imports); if Branch B keeps the latch inline there, AC-6's unit test is impossible — hence the move-to-plain-module step, which is a small relocation, not a redesign.

## Rollback

Revert the single PR. Branch A revert restores `goBack()` (spec goes back to flaky, product untouched). Branch B revert restores the old clear (spec goes back to red-on-main, product behavior unchanged elsewhere since only the failure-path release moves). No migrations, no data to repair.
