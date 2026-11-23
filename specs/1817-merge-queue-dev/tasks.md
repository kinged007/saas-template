# Tasks — #1817 merge-queue.yml (CI-CD piece 5)

## Phase 1 — Setup and tests first

- [ ] T001 [AC-8] scripts/test_merge_queue.py — trailer parse/validate tests (extract `Area:` + `Release-note:`, accept `api/web/db/infra`, reject missing/empty/invalid lines)
- [ ] T002 [AC-8, AC-9, AC-10, AC-11] scripts/test_merge_queue.py — selection tests (P0-then-FIFO by label time, stubbed events) and gate-mapping tests (each failing gate → exact label + one comment; gate 1 → no change; advisory approval logs without relabel or block)

## Phase 2 — Implementation

- [ ] T003 [AC-3, AC-9, AC-10, AC-11] scripts/merge_queue.py — selection + six gates in fixed order + `--dry-run` printing selection and per-gate results with zero mutations (gh/GitHub access behind one stubbed helper)
- [ ] T004 [AC-2, AC-5, AC-6] scripts/merge_queue.py — squash with explicit `--subject`/`--body` (no merge/rebase flags), close resolved issues naming the squash SHA, all auth via `FLEET_TOKEN`-supplied `GH_TOKEN`
- [ ] T005 [AC-4] scripts/merge_queue.py — red-branch path: rerun failed jobs once, then `git revert` newest squash keeping the revert line + run URL, reopen resolved issues with `agent:ci-fix` + run URL, halt until green
- [ ] T006 [P] [AC-1, AC-12] .github/workflows/merge-queue.yml — four triggers (`pull_request_target` labeled, `workflow_run` on `ci`, 30-min `schedule`, `workflow_dispatch`), `concurrency: { group: merge-queue, cancel-in-progress: false }`, single job calling the script; contains `group: merge-queue`, `--squash`, `--body`, `git revert`, `gh issue close`; contains no `--merge`, `--rebase`, `secrets.GITHUB_TOKEN`

## Phase 3 — Polish

- [ ] T007 [AC-7] smoke test — `python3 scripts/merge_queue.py --dry-run` against the live repo prints the selected PR and each gate result; verify zero mutations (`git status --short` clean, no label/comment/run changes)
- [ ] T008 [polish] quality gate — `python3 scripts/test_merge_queue.py` passes, `make label-contract` passes, new files end with a newline (trailing-newline CI job), `git status --short` shows only the three new files
