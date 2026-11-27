# Plan: source-guard — only `staging` may merge into `main` (issue #1874)

**Spec source:** `specs/1874-source-guard/spec.md` (Status: Draft, no open markers; requirements taken from it, not re-derived from the issue body).
**Area context:** missing — the issue carries no `area:` label and the repo has no `.agents/areas/` index (confirmed by triage; key files listed there were used instead).

## Approach

Build a small trusted guard in the style of the existing `branch-guard` pair (workflow + script + stubbed-`gh` self-test):

1. **New workflow `.github/workflows/source-guard.yml`** (workflow name and job name both `source-guard`, so the verdict appears as one selectable required check for the `main` ruleset — AC-6). Trigger `pull_request_target` on `opened`, `reopened`, `synchronize`, `edited` with `branches: [main]` (base filter), plus a job-level `if: github.event.pull_request.base.ref == 'main'` as defense. `pull_request_target` runs the workflow from the base branch, so a PR that edits the guard is still evaluated by the trusted version (AC-5). The workflow never checks out the PR head and executes no PR-supplied code.
2. **Decision logic in `scripts/source-guard.sh`** (pure, no network): inputs are base ref, head ref, head repo full name, base repo full name. Pass (exit 0, no side effects) only when head ref is `staging` **and** head repo equals base repo; a fork branch coincidentally named `staging` fails. Any other head fails and the workflow glue retargets with `gh pr edit <n> --base dev` and posts one comment carrying an HTML marker (`<!-- source-guard -->`); the glue lists existing comments first and skips posting when the marker is already present (comment-once, AC-1/AC-4). Putting the decision in a script mirrors `scripts/branch-guard.sh` and makes the offline self-test possible.
3. **Credential: the workflow's `GITHUB_TOKEN` with `pull-requests: write`** (plus `contents: read`), not `FLEET_TOKEN`. Rationale: least privilege per Story 4 (the guard needs no push/merge power, unlike `merge-queue.yml` which uses `FLEET_TOKEN`); no secret dependency; `pull_request_target` still runs trusted code. Risk R-1 below records the one thing to verify (fork-PR retarget under `GITHUB_TOKEN`).
4. **Self-test `scripts/source-guard.test.sh`** in the `scripts/branch-guard.test.sh` pattern: a `gh` stub on `PATH` that records `pr edit` / `pr comment` calls, no network. Cases map 1:1 to AC-1/AC-2/AC-3/AC-4 plus comment-once and no-PR-code-execution assertions. Wired into `ci.yml` as a new job following the existing `release-notes` job pattern (checkout + `bash scripts/source-guard.test.sh`).
5. **Docs:** one rule line in `docs/FLEET.md` Branch model ("Only `staging` is merged into `main`; `source-guard.yml` enforces it") and one matching check in `docs/FLEET.md` (Enforcement table).

Why this shape: the issue explicitly rules out head-branch rulesets (GitHub cannot express them) and mandates the `pull_request_target`-from-base + `gh pr edit --base dev` mechanism, so there is no simpler design. Reusing the branch-guard script/test/CI pattern keeps the diff conventional.

## Files to change

- `.github/workflows/source-guard.yml` (new) — trigger, permissions, pass/retarget+comment glue. No checkout of the PR head (checkout base or none).
- `scripts/source-guard.sh` (new) — pure decision function: `(base_ref, head_ref, head_repo, base_repo) -> pass/fail`; owns the same-repo-`staging` rule and the fork same-name edge case.
- `scripts/source-guard.test.sh` (new) — offline self-test with stubbed `gh`; cases for AC-1, AC-2, AC-3, AC-4, comment-once, no-checkout/no-exec.
- `.github/workflows/ci.yml` (edit) — new `source-guard-test` job following the `release-notes` job pattern so the self-test runs in CI (AC-7).
- `docs/FLEET.md` (edit, Branch model) — add rule: "Only `staging` is merged into `main`; `source-guard.yml` enforces it" (AC-8).
- `docs/FLEET.md` (edit) — add the matching check with a `grep` verification command (AC-8).

## Data and contract changes

None. No public interfaces, schemas, persisted data, config keys, or dependencies. The only new contract surface is the required-check name `source-guard` (consumed by the maintainer-applied ruleset, out of scope) and the comment marker `<!-- source-guard -->` used for comment-once dedup.

## Test plan

Tests first, per AC (all in `scripts/source-guard.test.sh` with stubbed `gh`, no network):

- AC-1: feature-branch head to `main` → decision fails, stub records one `pr edit --base dev` and exactly one guidance comment.
- AC-2: same-repo `staging` head to `main` → pass, stub records no edit and no comment.
- AC-3: bases `dev` and `staging` → guard takes no action (workflow filter + script guard both return ignore).
- AC-4: fork head (including fork branch named `staging`) to `main` → fail + retarget + one comment.
- AC-5: fixture PR that edits `source-guard.yml`/`source-guard.sh` is evaluated by the checked-in (trusted) script; assert the evaluation path never references the PR head (no checkout of head, no `eval`/`source` of PR content).
- AC-6: assert workflow file contains `name: source-guard` and job `source-guard` (greppable check name).
- AC-7: self-test exits 0 locally; `ci.yml` contains the new job (grep for `source-guard.test.sh`).
- AC-8: grep docs for the rule sentence and the check.

Smoke test (smallest real run of the built artifact): `bash scripts/source-guard.test.sh` from the repo root, plus `bash -n` on both new scripts and a YAML parse of the new workflow — no network, no Actions run needed.

## Risks

- R-1: `GITHUB_TOKEN` with `pull-requests: write` may not retarget a fork PR's base in all cases; mitigation: the self-test cannot cover live permissions, so the first real fork-PR event after merge is watched, with fallback to `FLEET_TOKEN` (one-line permission/env change, same mechanism as `merge-queue.yml`).
- R-2: the retarget itself (`--base dev`) fires new PR events; mitigation: after retarget the base is `dev`, which the trigger filter ignores — no loop. The plan asserts this in the self-test (already-retargeted PR ignored).
- R-3: `edited` events on the PR body could race with the marker check and double-comment; mitigation: marker check immediately precedes the comment call in the same step.
- R-4: none; the check lives in one table in `docs/FLEET.md`.

## Rollback

Revert the implementing PR (or, if already promoted, `git revert` it on `dev`): deleting `source-guard.yml` removes the check (ruleset will show it missing until the maintainer deselects it), removing the `ci.yml` job and the two scripts removes the test, and the two doc lines are reverted with it. No data migration, no state to clean; already-retargeted PRs keep their (correct) `dev` base.
