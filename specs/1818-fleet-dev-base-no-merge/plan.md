# Plan: Fleet builds target dev, review stops merging (#1818)

Spec: `specs/1818-fleet-dev-base-no-merge/spec.md` (Draft; written from the issue
description + owner sequencing comment + `docs/architecture/CI-CD.md` §4.2/§9 —
no spec-stage questions were needed). No `plan-check` revise verdict exists, so
this is a fresh plan, not a fix-up.

## Approach

Five small mechanical edits, no product code. The brief files are the entire
change surface:

1. `.agents/work-on-issues.md` §8: hardcode the integration branch — branch
   from `dev`, `gh pr create --base dev`; delete the `defaultBranchRef` lookup
   and the "resolve the base first (never assume)" prose.
2. `.agents/review_pr.md` §7: approval becomes `gh pr review <n> --approve`
   plus an approval comment carrying the verdict line and the approved head SHA
   (resolved via `gh pr view`), then add `agent:merge`, remove `in-progress`.
   Delete `gh pr merge` from the brief. High-risk path (step 3, `needs-human`)
   and escalation (§6) stay byte-identical.
3. `.github/pull_request_template.md`: add literal `Area: ` and `Release-note: `
   lines at line start in the Release-note section. The CICD-13 check greps
   `^Area: |^Release-note: `, so the existing bold `**Area:**` line alone does
   not satisfy it — the machine-read lines must be plain line-start text.
4. `docs/FLEET_LABELS.md`: `agent:merge` row becomes "approved, waiting for
   `merge-queue.yml`", moved from the starts-no-work list to the consumed
   table citing `.agents/review_pr.md` (sets the label; exists) and
   `merge-queue.yml` (consumes it; skipped by rule 2 until piece 5 lands).
5. `scripts/check-label-contract.sh`: remove `agent:merge` from `REQUIRED_DEAD`.
   Without this, AC-5 is unsatisfiable: rule 3 forces `agent:merge` to stay in
   the starts-no-work list, which contradicts FR-008's new meaning. This is the
   only file outside the four the issue names, and only AC-5 requires it.

Base of the built PR is `main` (CI-CD.md §9 row 2; fleet reads its brief from
the default branch). Sequencing is a build-stage gate, not a code gate: the PR
must carry `needs-human` and must not merge before #1817 (piece 5).

## Files to change

- `.agents/work-on-issues.md` §8 (~lines 171-180) — dev base, drop lookup.
- `.agents/review_pr.md` §7 (lines 245-259) — approve+comment+label, no merge.
- `.github/pull_request_template.md` Release-note section (line ~10) — two
  machine-read lines.
- `docs/FLEET_LABELS.md` `agent:merge` row (line 31) + starts-no-work list
  (lines 69-72) — new meaning.
- `scripts/check-label-contract.sh` `REQUIRED_DEAD` (line ~24) — drop
  `agent:merge` so the AC-5 check can pass.

## Data and contract changes

No product interfaces, schemas, persisted data, config, or dependencies change.
Contract changes (fleet-process only): `agent:merge` meaning (dead trigger →
approved, waiting for merge queue); build-brief base (`dev`, no lookup);
review-brief approval output (review event + comment + label, never merge);
PR-template machine lines (`Area:` / `Release-note:`).

## Test plan

The compliance checks in `docs/architecture/COMPLIANCE-CHECKLIST.md` (lines
19-22) are the tests; run them red-before / green-after, plus:

- AC-1: CICD-10 greps (`--base dev` present, `defaultBranchRef` absent).
- AC-2: CICD-11 grep (`gh pr merge` absent from `.agents/`).
- AC-3: CICD-12 greps (`agent:merge` + head-SHA mention in `review_pr.md`).
- AC-4: CICD-13 grep (`^Area: ` and `^Release-note: ` in the template).
- AC-5: `make label-contract` (the #1811 check; source: `Makefile:144`,
  `docs/FLEET_LABELS.md:5`, CI job `ci.yml:122`).
- AC-6/AC-7: manual dry-walk trace of the new §7 approval path and the
  unchanged high-risk path; record the trace in the PR body (docs-only change,
  no live PR to exercise).
- AC-8: build-stage gate — PR carries `needs-human`, unmerged until #1817.
- Smoke test: `make label-contract` green plus the `trailing-newline` CI loop
  (`ci.yml:129-142`) run locally over the touched files — these are the only CI
  jobs whose inputs this change alters. Full lint/test/build suites cover
  product code this piece does not touch.

## Risks

- Behaviour flips fleet-wide the moment this lands on `main`: every later
  approval sets `agent:merge` with no queue consuming it until #1817 lands —
  hence the `needs-human` sequencing gate (FR-009). Mitigation is process, not
  code: do not merge early.
- `review_pr.md:5` and `docs/FLEET_LABELS.md:59-61` describe `agent:done` as
  part of the old approval path; if the rewritten §7 drops `agent:done`, those
  sentences become stale. The build sweeps `agent:merge`/`agent:done`
  references for contradictions (T006).
- Stale-approval edge (spec): commits landing after approval invalidate the
  recorded head SHA; enforcement is queue-side (piece 5), not here.

## Rollback

Revert the single built PR (docs-only, no migrations, no data). Approvals
granted while the new brief is live would carry `agent:merge` with no consumer
until #1817 lands; the owner merges by hand in that window per the unchanged
high-risk/operator path.
