# Plan: promote.yml moves a verified dev SHA to staging and opens the staging→main promotion PR

Spec: `specs/1873-promote-staging-main/spec.md` (Status: Clarified; requirements taken from the spec, which restates the issue's acceptance criteria).
Area context: missing — no `.agents/areas/` index exists in this checkout. This plan derives from `docs/architecture/CI-CD.md` §§4.5–4.6, 6–9, `docs/architecture/COMPLIANCE-CHECKLIST.md` rows CICD-26/27/28, and the sibling workflows/scripts in `.github/workflows/` and `scripts/`. No prior `plan-check` revise verdict exists (only triage + spec comments), so nothing is being fixed up.

## Approach

Follow the repo's own convention: thin workflow, logic in a script. `merge-queue.yml` only declares triggers/concurrency and calls `scripts/merge_queue.py`; `branch-guard.yml` only calls `scripts/branch-guard.sh`. So:

- `.github/workflows/promote.yml` declares `schedule` (daily 04:00 UTC) + `workflow_dispatch`, a `concurrency: promote` group (serializes overlapping scheduled/manual runs — spec edge case), minimal `contents: read` permission, and four jobs: `freeze` → `verify-ci` + `verify-e2e` (reusable-workflow calls with the frozen SHA) → `promote` (`needs:` both verifiers) / `blocked` (on verifier failure).
- `scripts/promote.sh` holds every mutation (contains-check, merge, push, PR open-or-update, blocked-issue open-or-update) with all `gh`/`git` calls going through one runner function so `scripts/promote.test.sh` can stub `gh` with no network — the same pattern as `scripts/branch-guard.test.sh`.
- Every push and every `gh pr`/`gh issue` operation authenticates with `FLEET_TOKEN` (never `GITHUB_TOKEN`); no step names `main` as a push target. `e2e.yml` and `ci.yml` already accept `workflow_call` input `sha` and check out `inputs.sha` in every job (verified in this checkout), so AC-2 needs no changes to those files.
- Sequencing per the issue note and spec clarification: the workflow lands on `dev` first (the current default branch, so `schedule` fires); the first manual promotion carries it to `main` before the default-branch switch.
- Assumption (non-blocking question Q-1 below): the blocked-promotion issue is labelled `agent:triage`, the label CI-CD.md §4.5 step 3 names. The spec clarification mentions a `loop-triage` label, but no such label exists in the repo and labels must not be created.

## Files to change

- `.github/workflows/promote.yml` (new) — triggers, concurrency, `freeze` / `verify-ci` / `verify-e2e` / `promote` / `blocked` jobs; `GH_TOKEN: ${{ secrets.FLEET_TOKEN }}` on every mutating step; PR body from `make release-notes BASE=main HEAD=staging` plus frozen SHA and both verification run URLs.
- `scripts/promote.sh` (new) — freeze (record `dev` HEAD; `git merge-base --is-ancestor` no-op exit when `staging` already contains it), merge `Promote dev@<sha7>` into `staging` and push, open-or-update the single `staging → main` PR (regenerate body each run), open-or-update the single `Promotion blocked at <sha>` issue.
- `scripts/promote.test.sh` (new) — hermetic self-test with stubbed `gh` and a fixture repo: green path (staging advances via merge commit, PR created then updated not duplicated), red path (staging untouched, blocked issue created then updated), no-op path (zero mutations). Modelled on `scripts/branch-guard.test.sh`.
- `.github/workflows/ci.yml` (edit) — add one job running `bash scripts/promote.test.sh` with `ref: ${{ inputs.sha || github.sha }}`, mirroring the existing `release-notes` job that runs `bash scripts/release-notes.test.sh`.

## Data and contract changes

None. No models, migrations, API shapes, or persisted data change. No new secrets: the workflow reuses the existing `FLEET_TOKEN` repository secret. No new labels.

## Test plan

Write `scripts/promote.test.sh` first: green (AC-3, AC-4), red (AC-5), no-op (AC-6) paths, all hermetic. Static checks in the test or beside it cover the trigger/job-graph/credential properties: `schedule` + `workflow_dispatch` present (AC-1, CICD-26), staging-move job `needs:` both verifier jobs and both called workflows check out `inputs.sha` (AC-2, CICD-27), no `secrets.GITHUB_TOKEN` in push/PR steps (AC-7, CICD-28), no push to `main` in any outcome (AC-8). Smoke test: run `bash scripts/promote.test.sh` locally with no network and observe it pass; then `bash scripts/release-notes.test.sh` and `bash scripts/branch-guard.test.sh` still pass (no regressions in sibling self-tests).

## Risks

- A wrong token or ref in one step silently fakes verification (pushes with `GITHUB_TOKEN` do not trigger downstream workflows — CI-CD.md §7). Mitigated by AC-7 greps and keeping every mutation inside `scripts/promote.sh` where the stub test asserts the token env.
- `e2e.yml` runs Playwright with `--with-deps`; each promotion costs a full e2e run. Accepted by the design (verify-before-move is the point).
- A promotion PR left unmerged grows as later runs regenerate its body. Intended per §4.5; maintainer merges it.

## Rollback

Revert the PR that lands these files: the scheduled promotion stops, and `staging`/`main` are untouched by the revert because the workflow never force-pushes and never writes `main`. If a bad promotion already merged to `staging`, fix forward on `dev` (revert the slice there) and let the next promotion carry the revert — never commit directly to `staging`.
