# Tasks: #1818 fleet builds target dev, review stops merging

## Phase 1 — Setup and red-state tests first

- [x] T001 [AC-1, AC-2, AC-3, AC-4, AC-5] docs/architecture/COMPLIANCE-CHECKLIST.md — ran the CICD-10–13 greps and `make label-contract` to record the red baseline before editing (CICD-10/13 red as expected; label-contract green).

## Phase 2 — Implementation

- [x] T002 [P] [AC-1] .agents/work-on-issues.md — §8: branch from `dev`, `gh pr create --base dev`; deleted the `defaultBranchRef` lookup and "resolve the base" prose. Also tells the builder to fill the `Area:` / `Release-note:` lines, one line each (owner dispatch 20:29).
- [x] T003 [P] .agents/review_pr.md — §7: `gh pr merge <n> --merge` → `--squash`; merge kept. (Text fixed per owner scope update 19:16: the no-merge handoff — approve event, verdict/SHA comment, `agent:merge` — moves to #1817 with the merge queue. Step-1 skip list, step-3 high-risk path and §6 escalation untouched.)
- [x] T004 [P] [AC-4] .github/pull_request_template.md — Release-note section: added line-start `Area: <api|web|db|infra>` and `Release-note: <one line>` machine-read lines (kept the allowed-values guidance as an HTML comment).
- [x] T005 DEFERRED to #1817 per owner scope update 19:16 (queue piece): `docs/FLEET_LABELS.md` `agent:merge` row + `scripts/check-label-contract.sh` `REQUIRED_DEAD` stay untouched — with direct merge kept, no producer/consumer exists yet, so the queue-waiting meaning would be false against this diff. (Original text assumed the no-merge handoff.)
- [x] T006 sweep done, no edits needed: with the merge kept, `review_pr.md:5` (`agent:done` on approval path), the step-1 skip list, and `FLEET_LABELS.md:59-61` ("then merge") all stay true; no `agent:merge` references were added so nothing contradicts the contract doc. (Original text assumed the handoff reword; scope update 19:16 removed its basis.)

## Phase 3 — Polish (verify, smoke, ship gated)

- [x] T007 [AC-1, AC-4] repo root — re-ran the CICD-10/CICD-13 greps, `make label-contract`, and the `trailing-newline` CI loop over touched files; all green. (CICD-11/12 intentionally unsatisfied: merge kept per scope update 19:16; handoff moves to #1817.)
- [x] T008 dry-walked the §7 approval path (file minors → `agent:done` → squash-merge → claim released) and the high-risk path (unchanged: `needs-human` + `agent:done`, owner merges); both traces recorded in the PR body.
- [x] T009 PR — opened #1830 against base `dev` (default branch; scope update 19:16 — original `main` text fixed), no #1817 wait: merge as soon as green and approved; `risk:high` so the maintainer merges (PR carries `needs-human` + `agent:verify`). (Original "do not merge before #1817" sequencing removed by scope update.)
