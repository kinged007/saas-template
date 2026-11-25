# Tasks: source-guard (issue #1874)

Phases: Setup and tests first, Implementation, Polish. Every AC appears in at least one task.

## Setup and tests first

- [x] T001 [P] [AC-7] scripts/source-guard.test.sh — scaffold stubbed-`gh` harness in the `scripts/branch-guard.test.sh` pattern (PATH shim recording `pr edit`/`pr comment`, no network) with failing-first cases for AC-1, AC-2, AC-3, AC-4, plus the AC-6/AC-7/AC-8 grep assertions (check name, `ci.yml` wiring, docs lines)
- [x] T002 [P] [AC-5] scripts/source-guard.test.sh — add trusted-logic cases: PR editing the guard still evaluated by the checked-in script; no checkout of the PR head and no execution of PR content; closed/merged-PR short-circuit causes no `gh` calls
- [x] T003 [P] [AC-8] docs/FLEET.md — confirm the Branch model anchor line in the doc

## Implementation

- [x] T004 [AC-1,AC-2,AC-4] scripts/source-guard.sh — pure decision function over (base_ref, head_ref, head_repo, base_repo): pass only for same-repo `staging` head; fork same-name head fails
- [x] T005 [AC-1,AC-4] .github/workflows/source-guard.yml — `pull_request_target` on opened/reopened/synchronize/edited for base `main`, `pull-requests: write` permission, fail path retargets with `gh pr edit --base dev` and posts the one guidance comment with `<!-- source-guard -->` dedup; no checkout of the PR head; both steps short-circuit when the PR is no longer open
- [x] T006 [AC-2,AC-3] .github/workflows/source-guard.yml — pass path (same-repo `staging` head) exits 0 with no side effects; non-`main` bases ignored via trigger filter plus job-level `if`
- [x] T007 [AC-6] .github/workflows/source-guard.yml — workflow name and job name both `source-guard` so the verdict is one selectable required check
- [x] T008 [AC-7] .github/workflows/ci.yml — add `source-guard-test` job following the `release-notes` job pattern so the self-test runs in CI
- [x] T009 [AC-8] docs/FLEET.md — add the Branch model rule sentence and the matching check with a grep verification command

## Polish

- [x] T010 [AC-5] scripts/source-guard.sh + .github/workflows/source-guard.yml — re-verify no PR-head checkout and no PR-code execution in the final diff (read the workflow steps end to end)
- [x] T011 [polish] repo root — smoke test: `bash scripts/source-guard.test.sh`, `bash -n` on both new scripts, YAML parse of the new workflow
- [x] T012 [polish] repo root — quality gate for a workflows+scripts change: self-test, `./scripts/check-label-contract.sh`, trailing-newline check on touched files (see `ci.yml` `trailing-newline` job)
