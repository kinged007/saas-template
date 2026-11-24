# CI/CD compliance checklist

> **Checks:** [CI-CD.md](CI-CD.md) · **Revision:** 2026-11-20
> Each item names the section it comes from and a command that verifies it, run from the repo
> root. An implementer checks off the items its PR touches and pastes the list into the PR
> body. A reviewer re-runs the commands rather than trusting the ticks.

`REPO` below is `kinged007/saas-template`.

## Branches and settings

- [ ] **CICD-01** `dev` and `staging` exist (§2) — `gh api repos/$REPO/branches/dev --jq .name && gh api repos/$REPO/branches/staging --jq .name`
- [ ] **CICD-02** the default branch is `dev` (§2 rule 2) — `gh repo view --json defaultBranchRef -q .defaultBranchRef.name` prints `dev`
- [ ] **CICD-03** rebase merge is off; `delete_branch_on_merge` stays `false` until `staging` is excluded (§9 piece 1, §8 step 3) — `gh api repos/$REPO --jq '.allow_rebase_merge'` prints `false`; `.delete_branch_on_merge` prints `false`
- [ ] **CICD-04** `FLEET_TOKEN` secret exists (§7) — `gh secret list | grep -w FLEET_TOKEN`

## Fleet briefs

- [ ] **CICD-10** build agents open PRs against `dev` (§4.2) — `grep -n -- '--base dev' .agents/work-on-issues.md` matches; `grep -n 'defaultBranchRef' .agents/work-on-issues.md` returns nothing
- [ ] **CICD-11** no agent brief merges a PR (§3) — `grep -rn 'gh pr merge' .agents/` returns nothing
- [ ] **CICD-12** approval sets `agent:merge` and records the approved head SHA (§4.2) — `grep -n 'agent:merge' .agents/review_pr.md` and `grep -n -i 'head SHA' .agents/review_pr.md` both match
- [ ] **CICD-13** PR template has machine-read lines (§4.2) — `grep -nE '^Area: |^Release-note: ' .github/pull_request_template.md` matches both
- [ ] **CICD-14** fleet assignment queries do not use `@me` (§7) — checked in the Multica autopilot prompts; `grep -rn '@me' .agents/` returns nothing

## Workflows

- [ ] **CICD-20** `ci` runs on pushes to all three branches, on PRs into `dev`/`main`, and is callable with a pinned SHA (§9 piece 3) — `grep -n 'workflow_call' .github/workflows/ci.yml` and `grep -n 'inputs:' .github/workflows/ci.yml` both match; the `push.branches` list names `dev`, `staging` and `main` and `pull_request.branches` names `dev` and `main`
- [ ] **CICD-21** `e2e` is callable with a pinned SHA and runs on PRs into `main` (§9 piece 3) — `grep -n 'workflow_call' .github/workflows/e2e.yml` and `grep -n 'inputs:' .github/workflows/e2e.yml` both match; `grep -nE 'pull_request' .github/workflows/e2e.yml` matches
- [ ] **CICD-22** merge queue is serialized (§4.3) — `grep -n 'group: merge-queue' .github/workflows/merge-queue.yml`
- [ ] **CICD-23** merge queue squashes with an explicit body (§4.3) — `grep -n -- '--squash' .github/workflows/merge-queue.yml` and `grep -n -- '--body' .github/workflows/merge-queue.yml` both match; `grep -nE -- '--merge|--rebase' .github/workflows/merge-queue.yml` returns nothing
- [ ] **CICD-24** merge queue checks the approved SHA against the head (§4.3 check 5) — read the step; it fails on a mismatch and sets `agent:review`
- [ ] **CICD-25** red `dev` is auto-reverted with git's revert line (§4.4) — `grep -n 'git revert' .github/workflows/merge-queue.yml`
- [ ] **CICD-25a** merge queue closes linked issues after the squash (§4.3) — `grep -n 'gh issue close' .github/workflows/merge-queue.yml`
- [ ] **CICD-26** promotion has cron and manual triggers (§4.5, §6) — `grep -nE 'schedule:|workflow_dispatch' .github/workflows/promote.yml` matches both
- [ ] **CICD-27** promotion verifies the frozen SHA before it moves `staging` (§4.5 step 2) — the job that pushes `staging` has `needs:` on the jobs that call `ci.yml` and `e2e.yml` **and** both called workflows check out `inputs.sha` (`grep -n 'inputs.sha' .github/workflows/ci.yml` and the same in `e2e.yml`)
- [ ] **CICD-28** no workflow that pushes or opens a PR uses `GITHUB_TOKEN` for it (§7) — `grep -n 'secrets.GITHUB_TOKEN' .github/workflows/merge-queue.yml .github/workflows/promote.yml` returns nothing
- [ ] **CICD-29** branch guard covers all three branches (§7) — `grep -nE 'dev|staging|main' .github/workflows/branch-guard.yml`

## Scripts

- [ ] **CICD-30** `make release-notes` exists (§9 piece 4) — `make -n release-notes BASE=main HEAD=dev` exits 0
- [ ] **CICD-31** release notes drop reverted slices (§9 piece 4) — on a scratch branch, make a commit and revert it; `make release-notes BASE=<before> HEAD=<after>` lists neither
- [ ] **CICD-32** `make release-candidate` exists and is documented (§9 piece 8) — `make -n release-candidate SHA=HEAD` exits 0; `grep -n 'release-candidate' docs/OPERATIONS.md` matches

## History (run against the live branches)

- [ ] **CICD-40** `dev` first-parent commits are single-parent (§2) — `git log --first-parent --merges origin/staging..origin/dev` prints nothing
- [ ] **CICD-41** every non-revert `dev` commit carries both lines (§4.3) — `git log --format='%H %s%n%b' origin/staging..origin/dev` shows `Area:` and `Release-note:` under each non-`revert:` subject
- [ ] **CICD-42** `staging` and `main` move only by merge commits (§2 rule 5) — `git log --first-parent --no-merges <last-checked>..origin/main` prints nothing; same for `origin/staging`
- [ ] **CICD-43** no fix was committed to `staging` or `main` (§2 rule 3) — `git diff --quiet origin/staging origin/staging^2 && git diff --quiet origin/main origin/main^2`: each branch's tree equals the commit it last took in
