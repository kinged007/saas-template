# Plan: branch-guard.yml (issue #1838, fleet merge-queue piece)

Source: spec at `specs/1838-branch-guard/spec.md` (Status: Clarified). No
`plan-check` revise verdict exists, so this is a fresh plan, not a fixup.

## Approach

One bash check script plus one workflow, following the existing
`scripts/check-template-paths.sh` + `scripts/check-template-paths.test.sh`
fixture-repo precedent (confirmed in repo; triage comment settles this).

- `scripts/branch-guard.sh <branch> <before> <after>` does all rule logic with
  git plumbing only, so it is testable offline. Why a script and not inline
  YAML: FR-008 requires versioned logic with tests, and YAML cannot build
  fixture repos. Workflow stays thin: checkout with `fetch-depth: 0`, call the
  script, and on failure open-or-update one `needs-human` issue per branch.
- Range handling: `git rev-list --first-parent <before>..<after>`; empty range
  passes. Force push: `git merge-base --is-ancestor <before> <after>` fails
  (plus the workflow also fails fast on `github.event.forced`); deletion push
  (`after` all zeros) fails. This keeps history (`462dfea2d`, `2f1e27fd7`)
  unchecked because only the pushed range is listed (FR-006).
- `dev`: each listed commit must have exactly one parent and a message with
  `Area:` and `Release-note:` trailer lines, or be a revert (case-insensitive
  `revert:` subject or the VCS default `Revert "..."` subject, per spec
  clarification). Merge commits on `dev` fail the single-parent test. Trailer
  matching reuses the `scripts/merge_queue.py` `AREA_RE` shape
  (`VALID_AREAS = ("api", "web", "db", "infra")` confirmed there).
- `staging`: each listed commit must be a merge whose second parent
  (`git rev-list --parents -n1` field 3) is an ancestor of the current `dev`
  head. `main`: same against the current `staging` head. Ancestor-at-check-time
  is the spec's chosen definition of "at merge time" (exact equality is
  unrecoverable later).
- Issue mechanics: title prefix `[branch-guard] <branch> violation`, found via
  `gh issue list --search`; update the open one, else create with label
  `needs-human` (label confirmed to exist). Guard never pushes, so the default
  workflow credential is enough (no `FLEET_TOKEN`, no conflict with the rule that the merge queue never uses `GITHUB_TOKEN`).
- First run: piece 7 bases on `dev` (docs/FLEET.md, confirmed); the
  introducing PR squash-merges with `Area: infra` + one `Release-note:` line,
  so its own range passes the `dev` rule and the post-merge push shows green.

## Files to change

- `scripts/branch-guard.sh` (new) — rule checks: FF/deletion gate, per-branch
  first-parent range validation, machine-readable failure output
  (offending SHA + rule per line) for the workflow's issue body.
- `scripts/branch-guard.test.sh` (new) — fixture-repo suite: good+bad case per
  branch, force push, empty range, revert pass, merge-on-dev fail.
- `.github/workflows/branch-guard.yml` (new) — `push` on `dev`, `staging`,
  `main`; full history checkout; run script with `github.ref_name`,
  `github.event.before/after/forced`; failure step opens/updates the
  per-branch `needs-human` issue.

## Data and contract changes

None for schemas, persisted data, config files, or dependencies. One workflow
permission note: `branch-guard.yml` needs `contents: read` + `issues: write`
(the default `GITHUB_TOKEN` suffices since the guard never pushes or merges).

## Test plan

Tests first (fixture repo in `scripts/branch-guard.test.sh`, run with
`bash scripts/branch-guard.test.sh` — the same invocation shape as the
existing template-paths self-test that `ci.yml` runs):
- AC-1: trailer-less single-parent push to `dev` → exit non-zero naming SHA.
- AC-2: well-formed `dev` commits + a `revert:` commit → exit 0.
- AC-3: non-`dev` merge into `staging` → fail; `dev`-head merge → pass.
- AC-4: non-`staging` merge into `main` → fail; `staging`-head merge → pass.
- AC-5: rewritten tip (non-ancestor `before`) → fail as non-fast-forward.
- AC-6: range not containing the historic trailer-less commits → pass;
  range listing them (simulated old `before`) → fail, proving range scoping.
- AC-7: covered at workflow level (title-prefix search → update, not create);
  asserted by dry-run of the issue step if feasible, else verified on first
  real violation.
- AC-8: suite passes as a whole (`bash` exit 0).
- AC-9: `grep -nE 'dev|staging|main' .github/workflows/branch-guard.yml`
  matches (the exact coverage command).
- Smoke test: run the script against a real range in this checkout
  (e.g. `bash scripts/branch-guard.sh dev <before> <after>` on recent `dev`
  history) plus the full test file; no app boot or preview needed (spec
  out-of-scope: no click-through).

## Risks

- Ancestor-at-check-time approximation: a `staging` merge of a branch that
  only reached `dev` after the merge passes. Accepted by spec clarification;
  ordering races resolve in favour of branch state at run time.
- Concurrent violating pushes to one branch may open two issues before either
  run sees the other; title-prefix update converges them on the next run.
- `github.event.before` can be all zeros on first push; script treats unknown
  `before` as full-range check of `after` (documented fallback, still green
  for well-formed history).

## Rollback

Revert the introducing squash commit on `dev` with `git revert` (the revert
commit itself passes the `dev` rule); deleting
`.github/workflows/branch-guard.yml` stops all future runs. No data migration
involved.
