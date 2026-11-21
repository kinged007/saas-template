# Tasks: #1807 — OAuth callback latch retry

Spec: `specs/1807-oauth-latch-retry/spec.md`. Branch A = bfcache (spec-only); Branch B = latch (product fix). T003 decides; only one branch's tasks then apply.

## Phase 1 — Setup and diagnose first

- [ ] T001 [AC-5] apps/web/e2e/oauth-callback.spec.ts — reproduce: run the single spec file to confirm the 1-vs-2 POST failure locally
- [ ] T002 [AC-3] apps/web/e2e/oauth-callback.spec.ts — diagnose: re-run the single spec with bfcache disabled (CDP) or a mount-effect log to decide Branch A vs Branch B
- [ ] T003 [AC-1] apps/web/e2e/oauth-callback.spec.ts — record the verdict (bfcache restore vs surviving latch) in a plan comment for the reviewer

## Phase 2 — Implementation (one branch only)

- [ ] T004 [AC-1, AC-3, AC-4] apps/web/e2e/oauth-callback.spec.ts — Branch A: replace click + goBack() with a non-restorable in-app re-navigation into /oauth/callback?code=, keep the two-POST assertion, add the one-line why-not-goBack() comment
- [ ] T005 [AC-1, AC-2] apps/web/src/components/AuthConfig.tsx — Branch B: make the failed-exchange latch release hold whether or not the view is still mounted, success-path latch unchanged
- [ ] T006 [P] [AC-6] apps/web/src/components/oauth-callback.ts — Branch B: relocate the latch read/write/clear into this plain module only if needed for node --test testability
- [ ] T007 [AC-6] apps/web/src/components/oauth-callback.test.ts — Branch B: add the release-after-teardown unit case (failed exchange, view gone, repeat visit retries)

## Phase 3 — Polish (docs, smoke test, quality gate)

- [ ] T008 [P] [AC-4] apps/web/e2e/oauth-callback.spec.ts — verify no skip or fixme marker remains on the retry spec
- [ ] T009 [smoke] apps/web/e2e/oauth-callback.spec.ts — smoke: targeted single-file playwright run passes
- [ ] T010 [AC-5] e2e CI — three consecutive full e2e runs green (local make web-test-e2e or .github/workflows/e2e.yml)
- [ ] T011 [P] [quality gate] repo root — run make web-build and make web-test, both green
