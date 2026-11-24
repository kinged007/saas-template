# Checklist: #1807 — plan quality

- [x] CHK001 Is AC-1 measurable? Yes — exactly two POSTs to /api/v1/auth/oauth/token across the two visits (T001, T004/T005, T010).
- [x] CHK002 Is AC-2 measurable? Yes — failure message visible and pending indicator absent on the repeat visit (T005 Branch B, T004 Branch A asserts the same terminal state).
- [x] CHK003 Is AC-3 testable without assuming the cause? Yes — T002 (bfcache-disabled run) decides Branch A vs B before any product edit.
- [x] CHK004 Does AC-4 have a task? Yes — T004 (comment) + T008 (verify no skip/fixme).
- [x] CHK005 Does AC-5 have a task? Yes — T010 (three consecutive full e2e runs); T001/T009 are the cheaper local runs.
- [x] CHK006 Does AC-6 have tasks on the latch branch only? Yes — T006 (testable placement) + T007 (unit case); correctly absent from Branch A.
- [x] CHK007 Does every FR have coverage? Yes — FR-001/FR-004 → AC-1 tasks; FR-002 → AC-2; FR-003 → T002–T004; FR-005 → T004/T008.
- [x] CHK008 Is the plan minimal (no unneeded tasks)? Yes — one branch's tasks are skipped by construction (T003 decides); no backend, timeout, success-path, or infra tasks; out-of-scope items from the spec appear nowhere in tasks.md.
- [x] CHK009 Are all named files/functions confirmed to exist? Yes — via grep/ls: apps/web/e2e/oauth-callback.spec.ts, apps/web/src/components/AuthConfig.tsx (consumedCode latch, .catch clear), apps/web/src/components/oauth-callback.ts, apps/web/src/components/oauth-callback.test.ts, Makefile targets web-build/web-test/web-test-e2e, .github/workflows/e2e.yml.
- [x] CHK010 Are the quality-gate commands from repo docs, not invented? Yes — make web-build / make web-test / make web-test-e2e from Makefile and root AGENTS.md; full e2e from .github/workflows/e2e.yml.
- [x] CHK011 Does the plan respect the "do not assume the latch" constraint? Yes — diagnose-first (T002/T003) precedes any product change.
- [x] CHK012 Does the plan forbid deleting/skipping the assertion? Yes — stated in plan Approach and Files, enforced by T008.
