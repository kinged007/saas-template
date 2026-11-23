# Tasks: #1818 fleet builds target dev, review stops merging

## Phase 1 — Setup and red-state tests first

- [ ] T001 [AC-1, AC-2, AC-3, AC-4, AC-5] docs/architecture/COMPLIANCE-CHECKLIST.md — run the CICD-10–13 grep checks and `make label-contract` to record the red baseline before editing.

## Phase 2 — Implementation

- [ ] T002 [P] [AC-1] .agents/work-on-issues.md — §8: branch from `dev`, `gh pr create --base dev`; delete the `defaultBranchRef` lookup and "resolve the base" prose.
- [ ] T003 [P] [AC-2, AC-3] .agents/review_pr.md — §7: approval submits `gh pr review <n> --approve`, posts verdict + approved head SHA comment, adds `agent:merge`, removes `in-progress`; delete `gh pr merge`; leave step 3 high-risk path and §6 escalation untouched.
- [ ] T004 [P] [AC-4] .github/pull_request_template.md — Release-note section: add line-start `Area: <api|web|db|infra>` and `Release-note: <one line>` machine-read lines.
- [ ] T005 [P] [AC-5] docs/FLEET_LABELS.md + scripts/check-label-contract.sh — `agent:merge` row means approved, waiting for `merge-queue.yml` (consumed table, not starts-no-work); drop `agent:merge` from `REQUIRED_DEAD` so the contract check passes.
- [ ] T006 [AC-2, AC-3] .agents/review_pr.md + docs/FLEET_LABELS.md — sweep `agent:merge`/`agent:done`/`gh pr merge` references for sentences the new §7 contradicts (e.g. old approval-path `agent:done` mentions); fix only contradictions.

## Phase 3 — Polish (verify, smoke, ship gated)

- [ ] T007 [AC-1, AC-2, AC-3, AC-4, AC-5] repo root — re-run the CICD-10–13 greps, `make label-contract`, and the `trailing-newline` CI loop over touched files; all green.
- [ ] T008 [AC-6, AC-7] .agents/review_pr.md — dry-walk the new approval path (review event + comment + label set + claim removed + no merge) and the high-risk path (human merge decision); record both traces in the PR body.
- [ ] T009 [AC-8] PR — open against base `main`, label `needs-human`, do not merge before #1817 (piece 5); retarget/merge timing owned by the maintainer.
