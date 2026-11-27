# Tasks: branch-guard.yml (#1838)

## Phase 1 — Setup and tests first

- [x] T001 [P] [AC-8] scripts/branch-guard.test.sh — fixture scaffold: throwaway repo with dev/staging/main branches plus pass/fail assert helpers (copies the scripts/check-template-paths.test.sh mktemp+trap shape).
- [x] T002 [AC-1, AC-2] scripts/branch-guard.test.sh — dev cases: trailer-less commit fails naming SHA; well-formed commits, a revert: commit and the VCS default revert subject pass; plus a merge commit on dev fails the single-parent test (plan-check F2).
- [x] T003 [AC-3, AC-4] scripts/branch-guard.test.sh — staging/main cases: wrong-parent merges fail naming the merge SHA; dev-head and staging-head merges pass.
- [x] T004 [AC-5, AC-6] scripts/branch-guard.test.sh — force-push case fails as non-fast-forward; empty range passes; range scoping proven against simulated historic trailer-less commits; deletion push (after all zeros) fails (plan-check F3).

## Phase 2 — Implementation

- [x] T005 [AC-1, AC-2, AC-6] scripts/branch-guard.sh — FF/deletion gate plus dev rule: first-parent range listing, single-parent and Area:/Release-note:/revert: message check.
- [x] T006 [AC-3, AC-4, AC-5] scripts/branch-guard.sh — staging/main rule: second-parent ancestor check against dev/staging head; non-fast-forward detection via merge-base.
- [x] T007 [AC-7, AC-9] .github/workflows/branch-guard.yml — push trigger on dev/staging/main, full-history checkout, script call with ref_name/before/after/forced, failure step that updates the open per-branch issue or creates it with needs-human.

## Phase 3 — Polish

- [x] T008 [P] [AC-9] docs/FLEET.md — verify the branch-guard coverage grep in `docs/FLEET.md` passes against branch-guard.yml (no doc edit unless the wording drifts).
- [x] T009 [P] [AC-8, AC-10] scripts/branch-guard.test.sh + live repo — smoke test: bash scripts/branch-guard.test.sh green plus one script run against a real pushed range; record first-run verification for the PR body; AC-7 update-not-duplicate covered by a stub-gh dry run of the workflow issue step inside the suite (plan-check F1).
- [ ] T010 [polish] repo quality gate — run make api-lint, make api-test, make db-check, make web-build, make web-test (from Makefile/ci.yml); shell scripts have no repo linter, so bash -n plus the test suite is the gate for the new files.
