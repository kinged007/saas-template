# Plan — #1618 ci: no GitHub Actions runs for PR #1610 head; reconcile the full-suite flake

No `spec.md` exists for this item (the repo has no `specs/` directory). Requirements come from the issue description and the owner's routing comment (2026-11, `kinged007`): state the cause from the API, give the exact config change and a guard that proves runs land, and reconcile the flake as a separate item without fixing it here.

## Acceptance criteria (derived)

- **AC-1** The cause is on record with API evidence.
- **AC-2** The `ci` workflow is active again (`gh api repos/kinged007/saas-template/actions/workflows/ci.yml --jq .state` prints `active`).
- **AC-3** Guard: the PR head of `auto/1618` gets at least one `ci` run with event `pull_request` for its exact head SHA, and that run includes the `web-e2e` job (which runs the two e2e specs PR #1610 added, now on `main`).
- **AC-4** The `signin-return-to.spec.ts:129` flake is reconciled as a separate item (#1508); `apps/web/e2e/signin-return-to.spec.ts` is not changed in this PR.
- **AC-5** `AGENTS.md` tells the next agent how to diagnose a PR head with zero check runs.

## Cause (AC-1, evidence collected 2026-11-12)

| Check | Result |
| --- | --- |
| `gh api repos/kinged007/saas-template/actions/workflows --jq '.workflows[]\|[.path,.state,.updated_at]'` | `.github/workflows/ci.yml  disabled_manually  2026-10-02T06:27:11Z` |
| `gh api 'repos/kinged007/saas-template/actions/runs?per_page=1'` | latest run `36972979131`, `auto/732`, created `2026-10-02T06:19:14Z` |
| `gh api 'repos/kinged007/saas-template/actions/runs?created=>2026-10-02T06:20:00Z' --jq .total_count` | `0` (no runs since, including pushes to `main` such as #1713) |
| `gh api repos/kinged007/saas-template/actions/permissions` | `{"enabled":true,"allowed_actions":"all"}` — Actions is on at repo level |
| `gh api repos/kinged007/saas-template/actions/runners --jq .total_count` | `0` — irrelevant: every job in `ci.yml` uses `runs-on: ubuntu-latest` (GitHub-hosted) |
| `gh api 'repos/kinged007/saas-template/actions/runs?head_sha=0f58d00…'` | `0`; PR #1610 (`auto/1583`, same-repo, not a fork) was opened 2026-10-10, after the disable |
| commit `0f58d00` check-suites | only `vercel`, `railway-app`, `appwrite`, `coder`, `render` (all `queued`) — third-party apps, not Actions |
| `gh api repos/kinged007/saas-template/branches/main/protection` | 403: private repo on a free user plan, so no required checks exist; nothing blocked the merge on missing CI |

**Cause:** someone disabled the `ci` workflow manually on 2026-10-02 at 06:27Z, eight minutes after its last run. A disabled workflow creates no runs for any event, so PR #1610 and every later PR and `main` push got no Actions checks. The fork/push path and the `auto/*` automation are not involved. The issue's #1617 comparison is not possible (#1617 is not a PR); the last PRs that did get runs (`auto/732`, `auto/628`, 2026-10-02) used the same same-repo `auto/*` path.

## Approach

1. Re-enable the workflow with one repository setting change (not a file change):
   `gh workflow enable ci --repo kinged007/saas-template`
2. Prove runs land: the PR that ships this plan (head branch `auto/1618`) is opened or pushed to after step 1. Check that its head SHA has a `ci` run with a `web-e2e` job. A push made before step 1 does not count; push a new commit (the AGENTS.md note) after enabling.
3. Reconcile the flake on #1508, which tracks the same spec file (sibling test at line 140, same `--workers=4` load pattern). Add the line-129 observation there; do not change the spec here.
4. Add a short CI note to `AGENTS.md` so a zero-check-run PR is diagnosed by checking the workflow state first.

No lasting automated guard is added: a disabled workflow cannot report on itself, and branch protection (required checks) is unavailable on this plan (403 above). The AGENTS.md note and the per-PR run check are the guard.

## Files to change

| Path | Change |
| --- | --- |
| `AGENTS.md` | Add a `## CI` section after `## Migrations`: `.github/workflows/ci.yml` runs on `pull_request` and pushes to `main`; if a PR head has no Actions check runs, run `gh workflow list --all --repo kinged007/saas-template` and look for `disabled_manually` before investigating anything else. |

Repository setting (not a file): workflow `ci` (id `363399628`) state → `active`.
Tracker (not a file): one comment on #1508.

## Data and contract changes

None in code, schemas, persisted data, config files or dependencies. One repository setting changes (workflow state). Re-enabling resumes GitHub Actions minute usage on this private repository.

## Test plan

Tests first, per AC:

- **AC-1** No test; the evidence table above is reproducible with the listed commands.
- **AC-2** Before: `gh api repos/kinged007/saas-template/actions/workflows/ci.yml --jq .state` prints `disabled_manually`. After step 1 it prints `active`.
- **AC-3** After pushing the AGENTS.md commit to `auto/1618` with the PR open:
  `SHA=$(gh pr view auto/1618 --repo kinged007/saas-template --json headRefOid --jq .headRefOid)`
  `gh api "repos/kinged007/saas-template/actions/runs?head_sha=$SHA&event=pull_request" --jq '.total_count'` ≥ 1, and
  `gh api "repos/kinged007/saas-template/actions/runs/<run_id>/jobs" --jq '.jobs[].name'` lists `web-e2e`. Record run URL and job conclusions in the PR body.
- **AC-4** `git diff main -- apps/web/e2e/signin-return-to.spec.ts` is empty; #1508 has the new comment.
- **AC-5** Reviewed by reading the diff.

Smoke test: the CI run on the PR head is itself the smallest real run of the built artifacts (`web-build`, `web-test`, `web-e2e`, `api-test`, `api-lint`, `db-check`). Locally, no code changes, so the quality gate is not required; if run, use the commands from `.github/workflows/ci.yml` and `AGENTS.md`: `cd apps/web && npm run build && npm test`, `cd apps/api && uv run ruff check . && uv run ruff format --check . && uv run pytest -q`, `make db-check`.

## Risks

- **The disable may have been intentional** (for example to save Actions minutes on a private repo after ~512 runs). Re-enabling resumes spend. See the non-blocking question in the plan comment; the build stage proceeds with "re-enable".
- **CI on `main` has not run for six weeks.** The first run may fail on drift merged without checks (PRs #1610–#1722). Failures in jobs unrelated to this change are recorded in the PR body and filed as separate items; they are not fixed in this PR.
- **The e2e flake may hit the first run.** `web-e2e` runs the full suite with default workers. If `signin-return-to.spec.ts` fails, re-run failed jobs once and note it on #1508.
- **Billing/quota.** If runs are created but jobs fail to start with a spending-limit message, the cause moves to billing; stop and escalate to the owner.

## Rollback

`gh workflow disable ci --repo kinged007/saas-template` restores the current state. Revert the `AGENTS.md` commit with `git revert`. The #1508 comment needs no rollback.
