# Tasks — #1618

## Phase 1: Setup and tests first

- [ ] T001 [AC-2] (repo setting) — record the before state: `gh api repos/kinged007/saas-template/actions/workflows/ci.yml --jq .state` prints `disabled_manually`
- [ ] T002 [AC-1] specs/1618-ci-runs-missing/plan.md — re-run the evidence commands in the Cause table; if any result differs (e.g. state already `active`), update the table before continuing

## Phase 2: Implementation

- [ ] T003 [AC-2] (repo setting) — `gh workflow enable ci --repo kinged007/saas-template`; confirm `.state` is `active`
- [ ] T004 [P] [AC-5] AGENTS.md — add the `## CI` section after `## Migrations` as described in plan.md
- [ ] T005 [P] [AC-4] (tracker, #1508) — comment with the PR #1610 review observation: `signin-return-to.spec.ts:129` failed once in a full-suite run (152 passed, 1 failed; expected `/api-keys?page=2`, got `/`), passed 26/26 in two isolated re-runs; same file and load pattern as #1508. Do not edit the spec.
- [ ] T006 [AC-3] (git) — commit T004 and push to `auto/1618` after T003; open the PR if none exists (PR body closes #1618)

## Phase 3: Polish

- [ ] T007 [AC-3] (verification) — for the PR head SHA, confirm ≥1 `pull_request` run of `ci` and a `web-e2e` job; put the run URL and per-job conclusions in the PR body
- [ ] T008 [AC-3] (triage) — for any failed job: re-run once; if `signin-return-to.spec.ts` fails, add it to #1508; other failures unrelated to this diff go into a new issue linked from the PR body
- [ ] T009 [AC-4] (verification) — `git diff main -- apps/web/e2e/signin-return-to.spec.ts` is empty
- [ ] T010 [Polish: quality gate] — `git diff main` touches only `AGENTS.md` and `specs/1618-ci-runs-missing/`; the CI run from T007 is the quality gate (commands from `.github/workflows/ci.yml`)
