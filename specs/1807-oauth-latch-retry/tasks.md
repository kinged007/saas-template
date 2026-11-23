# Tasks: #1807 — OAuth callback latch retry

Spec: `specs/1807-oauth-latch-retry/spec.md`. Branch A = round-trip never remounts (spec-only); Branch B = latch (product fix). T003 decides; only one branch's tasks then apply. T003 verdict (CI-trace evidence): Branch A, but the mechanism is React concurrent-transition batching, not bfcache — the click and goBack are same-document (no cross-document load in the CI trace network log), so bfcache never applies and its disable flag was a no-op. Branch B disproved by reading: `.catch` clears `consumedCode` before `setStatus`, and the local mutation check (see PR) confirms the spec bites on the latch.

## Phase 1 — Setup and diagnose first

- [x] T001 [AC-5] apps/web/e2e/oauth-callback.spec.ts — reproduce: single-spec runs are green locally (3x); the 1-vs-2 failure does not reproduce locally and was diagnosed from the CI `web-e2e-report` trace artifact of main run 45196720088 instead
- [x] T002 [AC-3] apps/web/e2e/oauth-callback.spec.ts — diagnose: CDP `navigatedWithinDocument` + `pageshow` log locally (same-document push/pop, no bfcache) and CI trace (one document load, one token POST, post-goBack expects passing in ~5ms with zero further network) decide Branch A vs Branch B
- [x] T003 [AC-1] apps/web/e2e/oauth-callback.spec.ts — verdict: transition batching reconciles instead of remounting (see head note); recorded in the PR, not a plan comment

## Phase 2 — Implementation (one branch only)

- [x] T004 [AC-1, AC-2, AC-3, AC-4] apps/web/e2e/oauth-callback.spec.ts — Branch A: keep click + goBack() but gate goBack on the painted login (proves the callback unmounted, so the return is a real remount); revert `expect.poll` to the immediate two-POST assertion keeping lines 114-115 terminal-state assertions unchanged; replace the why-not-goBack comment with the gate comment; remove the now-unneeded `BackForwardCache` disable from `apps/web/playwright.config.ts` (same-document traversals never touch bfcache)
- [ ] T005 [AC-1, AC-2] apps/web/src/components/AuthConfig.tsx — Branch B: SKIPPED (latch proven correct; no product change)
- [ ] T006 [P] [AC-6] apps/web/src/components/oauth-callback.ts — Branch B: SKIPPED (no latch move needed)
- [ ] T007 [AC-6] apps/web/src/components/oauth-callback.test.ts — Branch B: SKIPPED (Branch B disproved; latch coverage stays with the e2e mutation check)

## Phase 3 — Polish (docs, smoke test, quality gate)

- [x] T008 [P] [AC-4] apps/web/e2e/oauth-callback.spec.ts — verified: no skip/fixme marker on the retry spec (`grep -rn 'test.fixme\|test.skip' apps/web/e2e/oauth-callback.spec.ts` empty)
- [x] T009 [smoke] apps/web/e2e/oauth-callback.spec.ts — smoke: single-file run green 3x locally after the fix
- [x] T010 [AC-5] e2e CI — three consecutive full e2e runs green on PR head e579b3c (CI run 45236973006: initial + 2 reruns, all `completed/success`, web-e2e pass each time). Post-merge, confirm three green runs on main before merging anything else behind it
- [x] T011 [P] [quality gate] repo root — `make web-build` and `make web-test` both green (266 unit tests pass)
