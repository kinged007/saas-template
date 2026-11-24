# Tasks: promote.yml (issue #1873)

## Phase 1 — Setup and tests first

- [ ] T001 [AC-9] scripts/promote.test.sh — hermetic self-test scaffold with stubbed `gh` and fixture repo (no network), modelling on scripts/branch-guard.test.sh
- [ ] T002 [P] [AC-3, AC-4] scripts/promote.test.sh — green-path case: staging advances to frozen SHA via merge commit; one staging→main PR created, second run updates its body instead of opening another
- [ ] T003 [P] [AC-5] scripts/promote.test.sh — red-path case: staging ref unchanged; exactly one blocked-promotion issue names the frozen SHA with failed run links; rerun updates it
- [ ] T004 [P] [AC-6] scripts/promote.test.sh — no-op case: staging already contains frozen SHA; zero push/PR/issue calls, exit 0
- [ ] T005 [AC-1, AC-2, AC-7, AC-8] scripts/promote.test.sh — static assertions: schedule + workflow_dispatch triggers; staging-move job needs both verifier jobs; no GITHUB_TOKEN in push/PR steps; no write to main

## Phase 2 — Implementation

- [ ] T006 [AC-1] .github/workflows/promote.yml — schedule (daily 04:00 UTC) + workflow_dispatch triggers; concurrency group promote; contents: read
- [ ] T007 [AC-2] .github/workflows/promote.yml — freeze job outputs frozen SHA; verify-ci/verify-e2e call ci.yml/e2e.yml with sha (both already check out inputs.sha — confirm, do not edit them)
- [ ] T008 [AC-3, AC-4] scripts/promote.sh + .github/workflows/promote.yml — green path: merge frozen SHA into staging, push with FLEET_TOKEN, open-or-update staging→main PR with body from make release-notes BASE=main HEAD=staging plus frozen SHA and both run URLs
- [ ] T009 [AC-5] scripts/promote.sh + .github/workflows/promote.yml — red path: leave staging untouched; open-or-update one Promotion blocked at <sha> issue labelled agent:triage with failed run links
- [ ] T010 [AC-6] scripts/promote.sh — no-op exit before any mutation when staging already contains the frozen SHA
- [ ] T011 [AC-7, AC-8] .github/workflows/promote.yml + scripts/promote.sh — all pushes and gh pr/gh issue calls use FLEET_TOKEN; no step pushes to main
- [ ] T012 [AC-9] .github/workflows/ci.yml — add promote self-test job running bash scripts/promote.test.sh, mirroring the release-notes job

## Phase 3 — Polish

- [ ] T013 [P] [AC-9] run bash scripts/promote.test.sh locally with no network; confirm pass (smoke test)
- [ ] T014 [P] [polish] run bash scripts/release-notes.test.sh and bash scripts/branch-guard.test.sh; confirm no regressions
- [ ] T015 [polish] run the repo quality gate for the touched surface (ci.yml script jobs: label-contract, trailing-newline) and git status --short to confirm only the four intended files are staged
