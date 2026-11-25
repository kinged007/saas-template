# Plan — #1817 merge-queue.yml (fleet pieces)

**Spec:** `specs/1817-merge-queue-dev/spec.md` (Status: Clarified; 14 FRs, 12 ACs).
Requirements come from the spec; strategy background is `docs/FLEET.md`
(Merge rules, Red dev, Credentials) and `docs/FLEET.md`
(merge-queue checks, all grep-based, so the plan pins exact strings).

## Approach

One thin workflow plus one Python-stdlib script. The workflow
(`.github/workflows/merge-queue.yml`) declares only triggers, `concurrency`,
and a call to the script; all decision logic lives in
`scripts/merge_queue.py` so it runs locally with `--dry-run` and is unit
testable. Python (not bash) because the logic is JSON-heavy (selection by
label time, six gates, trailer parsing) and Python's stdlib `json` avoids a
`jq` dependency; `snake_case` so tests import it directly. No new
dependencies, no new labels, no changes to `ci.yml` (piece 3, #1816, owns it).

Key design points (all from the spec, not new decisions):

- **Selection (FR-003):** oldest `agent:merge` PR carrying `P0` by label-applied
  time, else oldest `agent:merge` PR. Label times come from the REST issue
  events API (`LabeledEvent.created_at`); the build task pins and verifies this.
- **Gates in fixed order (FR-004):** (1) latest `ci` on the integration-branch
  head is green; (2) base is the integration branch; (3) mergeable, no textual
  conflict; (4) all head-SHA checks green; (5) approval at head SHA
  (**advisory in Stage 1 — evaluated and logged, never blocks, never relabels**,
  per FR-007 and the spec's resolved clarification); (6) one valid `Area:` line
  plus one non-empty `Release-note:` line. Valid `Area:` values are
  `api / web / db / infra`, taken from `.github/pull_request_template.md`.
- **Gate failure (FR-005/006):** any gate except 1 → remove `agent:merge`,
  apply exactly the mapped label (`agent:revise` / `agent:rebase` /
  `agent:ci-fix` / `agent:review`), post exactly one comment naming the gate,
  evaluate the next candidate. Gate 1 red/stale → change nothing, exit; the
  next `ci` completion retriggers.
- **Merge (FR-008/009):** exactly `gh pr merge "$N" --squash --subject "$TITLE
  (#$N)" --body "Area: …\nRelease-note: …"`, then `gh issue close` on every
  issue the PR resolves (resolved = `closingIssuesReferences`; build pins this)
  with a comment naming the squash SHA. At most one merge per run; success ends
  the run so branch verification for the new head completes first.
- **Red integration branch (FR-010/011):** rerun failed jobs exactly once; if
  still red, `git revert` the newest squash commit (message keeps git's `This
  reverts commit <sha>.` line plus the failed run URL), reopen the resolved
  issue(s) with `agent:ci-fix` and the run URL, and merge nothing until green.
- **Auth (FR-012):** every push/merge uses `secrets.FLEET_TOKEN` (exported as
  `GH_TOKEN` for `gh`/`git`); the string `secrets.GITHUB_TOKEN` appears nowhere
  in the workflow.
- **Triggers (FR-001):** `pull_request_target` labeled `agent:merge`,
  `workflow_run` on `ci` completion, `schedule` every 30 min, `workflow_dispatch`;
  `concurrency: { group: merge-queue, cancel-in-progress: false }`.

## Files to change

- **New** `.github/workflows/merge-queue.yml` — four triggers, concurrency
  group, one job calling the script with `GH_TOKEN: ${{ secrets.FLEET_TOKEN }}`.
  Must contain the literal strings the compliance checklist greps for:
  `group: merge-queue`, `--squash`, `--body`, `git revert`, `gh issue close`,
  and must not contain `--merge`, `--rebase`, or `secrets.GITHUB_TOKEN`.
- **New** `scripts/merge_queue.py` — stdlib only (`argparse`, `json`,
  `subprocess`, `urllib`/`gh` CLI); subcommands for select/gates/merge/revert
  plus `--dry-run` (prints selection and per-gate results, performs zero
  mutations). All `gh`/*git* calls go through one helper so dry-run can stub it.
- **New** `scripts/test_merge_queue.py` — stdlib `unittest`, runnable with
  `python3 scripts/test_merge_queue.py`; imports `merge_queue` directly.
- No edits to existing files. `docs/FLEET.md` already lists
  `agent:merge`/`agent:ci-fix`/`agent:rebase`/`agent:revise`/`agent:review` in
  the starts-no-work list, and `make label-contract` only inspects `.agents/`,
  so no doc change is needed (verified by running it).

## Data and contract changes

None. No public interfaces, no schemas, no persisted data, no migrations, no
config keys, no dependencies. The workflow references the `FLEET_TOKEN` repo
secret, whose provisioning belongs to piece 1 (#1816-track sibling for
branches+secret); until it exists the workflow fails loudly at auth time and
merges nothing.

## Test plan

Tests first (T001–T002), then implementation (T003–T006):

| AC | Test |
|----|------|
| AC-8 | trailer parse/validate unit tests: `Area:` + `Release-note:` extraction, valid values `api/web/db/infra`, missing/empty/invalid cases |
| AC-8/9/10/11 | selection tests (P0-then-FIFO by label time, fixtures with stubbed events); gate-mapping tests (each failing gate → exact label + one comment; gate 1 → no change; advisory approval logs without relabel) |
| AC-2/4/5/6 | assert on the exact command strings the script builds (`--squash`, `--body`, no `--merge/--rebase`, `git revert` keeping the revert line, `gh issue close` naming the SHA, `GH_TOKEN` from `FLEET_TOKEN` only) with subprocess stubbed |
| AC-7 | smoke test: `python3 scripts/merge_queue.py --dry-run` against the live repo prints the selected PR and each gate result; repo state verified unchanged (`git status --short` clean, no label/comment/run changes) |

## Risks

- **Default branch is `dev`, not `main`.** `gh repo view` shows the default
  branch is `dev` and no `main`/`staging` branches exist yet. docs/FLEET.md assumes
  `main`-as-default, but the spec (FR-001) is branch-agnostic ("evaluated from
  the default branch"), so the workflow simply lives on the default branch —
  today that is `dev`. If piece 1 later makes `main` the default, the file
  moves with it. Assumption recorded; not a spec change.
- **Ordering:** needs piece 3 (#1816, `ci` on the integration branch) for
  gates 1/4 to have statuses to read, and piece 2 (#1818, `--base dev` briefs,
  `agent:merge` + `Area:`/`Release-note:` lines) for selection and gates 2/6
  to have inputs. Until both land, dry-run gates fail loudly rather than
  silently.
- **Approval-check wording vs FR-007:** the old checklist said check 5 "fails on a
  mismatch and sets `agent:review`", but the spec (FR-007 + resolved
  clarification) is explicit that Stage 1 approval is record-only. The plan
  follows the spec; the manual approval-check read will need that context.
- **Label-time pagination:** FIFO ordering depends on issue-events API results;
  implementation must paginate and filter `LabeledEvent`s for `agent:merge`.

## Rollback

This change is purely additive (one workflow + one script + tests). Rollback
is `git revert` of the landing squash commit; with the workflow gone the queue
stalls at `agent:merge` (the known failure mode in docs/FLEET.md: "fix the
workflow", nothing merges unverified). No data migration to undo.
