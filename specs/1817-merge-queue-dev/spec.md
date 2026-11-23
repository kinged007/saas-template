# Feature Specification: Merge queue squash-merges approved PRs into dev

**Issue**: #1817  **Status**: Clarified  **Areas**: none (area context missing)

## User Scenarios and Testing

### User Story 1 - Approved PR is squash-merged into dev (Priority: P1)

A reviewer has approved a PR targeting the integration branch and marked it
ready-to-merge; the merge automation picks it up, verifies the six merge
gates in order, squash-merges it with machine-readable trailers, and closes
the issues the PR resolves with a comment naming the resulting commit, so
approved work lands without a person performing the merge.

**Independent test**: mark a green, approved PR ready-to-merge, run the merge
automation, and observe the PR merged as exactly one commit carrying both
trailer lines and its resolved issues closed with the commit named.

**Acceptance scenarios**:

1. Given one ready-to-merge PR whose gates all pass, When the automation runs,
   Then it squash-merges that PR with the subject and trailer body defined
   below and closes each resolved issue with the new commit named.
2. Given several ready-to-merge PRs including at least one highest-priority
   one, When the automation selects, Then it selects the longest-waiting
   highest-priority PR, otherwise the longest-waiting ready-to-merge PR.
3. Given a ready-to-merge PR that fails one gate, When the automation evaluates
   it, Then it removes the ready-to-merge mark, applies exactly the label
   defined for that gate, posts exactly one comment naming the failed gate,
   and evaluates the next candidate.

### User Story 2 - Red integration branch is retried once, then reverted (Priority: P1)

The integration branch verification turns red after a squash-merge; the merge
automation retries the failed verification jobs once, and when the retry is
still red it undoes exactly the newest squash commit, reopens the resolved
issue with the fix mark and the failed run location, and resumes with the
next PR once the branch is green again, so one broken slice never blocks the
queue.

**Independent test**: force the branch verification red on the newest squash
commit with a persistently failing job, run the automation, and observe one
retry followed by a revert commit, a reopened issue carrying the fix mark and
run location, and the queue unblocked.

**Acceptance scenarios**:

1. Given a red branch verification caused by the newest squash commit, When
   the automation responds, Then it retries the failed jobs exactly once
   before any revert.
2. Given the retry is still red, When the automation reverts, Then the revert
   undoes exactly the newest squash commit, keeps the revert lineage line and
   the failed run location in its message, reopens the resolved issue with the
   fix mark and the run location, and continues only once the branch is green.
3. Given the retry turns green, When the automation observes it, Then it
   performs no revert and resumes normal merging.

### User Story 3 - Operator previews the merge decision safely (Priority: P2)

A maintainer or agent operator wants to know what the automation would do
without changing anything; running the check routine in preview mode prints
which PR would be selected and the pass/fail result of each gate, with no
merge, label, comment, close, revert, or push performed, so the decision is
auditable before it runs on a schedule.

**Independent test**: run the check routine in preview mode against the live
repository and observe the printed selection plus per-gate results with the
repository state unchanged.

**Acceptance scenarios**:

1. Given ready-to-merge PRs exist, When the routine runs in preview mode,
   Then it prints the PR it would select and each gate result, and performs
   no mutation of any kind.
2. Given the routine runs in preview mode, When it finishes, Then the PR,
   issue, label, branch, and run state are identical to before the run.

## Requirements

- **FR-001**: The merge automation MUST run when a PR is marked ready-to-merge,
  when branch verification for the integration branch completes, on a
  thirty-minute recurring schedule evaluated from the default branch, and on
  manual request.
- **FR-002**: The merge automation MUST allow at most one merge run at a time,
  never cancelling a run already in flight.
- **FR-003**: The automation MUST select the longest-waiting ready-to-merge PR
  carrying the highest-priority mark when one exists, otherwise the
  longest-waiting ready-to-merge PR, ordered by the time the ready-to-merge
  mark was applied.
- **FR-004**: The automation MUST evaluate the six merge gates in fixed order:
  (1) branch verification for the current integration-branch head is green,
  (2) the PR targets the integration branch, (3) the PR is mergeable without
  textual conflict, (4) every verification at the PR head revision is green,
  (5) the current head revision carries an approval, (6) the PR description
  carries one valid area line and one non-empty release-note line.
- **FR-005**: On any gate failure except gate 1, the automation MUST remove the
  ready-to-merge mark, apply exactly the gate's defined follow-up label, post
  exactly one comment naming the failed gate, and evaluate the next candidate.
- **FR-006**: When gate 1 fails (branch verification missing or not green for
  the current head), the automation MUST change no PR mark and merge nothing,
  exiting so the next branch-verification completion retries.
- **FR-007**: The approval gate MUST be advisory in the current single-identity
  stage: it is evaluated and its outcome is recorded, but it MUST NOT block a
  merge nor change any PR mark on its own.
- **FR-008**: A merge MUST be a squash producing exactly one commit whose
  subject names the PR title and number and whose body carries the area and
  release-note trailer lines taken from the PR description.
- **FR-009**: After a merge, the automation MUST close each issue the PR
  resolves with a comment naming the squash commit.
- **FR-010**: When branch verification on the integration branch is red, the
  automation MUST retry the failed jobs exactly once before any revert.
- **FR-011**: When the retry is still red, the automation MUST undo exactly
  the newest squash commit on the integration branch, keep the revert lineage
  line and the failed run location in the revert message, reopen the resolved
  issue with the fix mark and the run location, and resume merging only once
  the branch is green.
- **FR-012**: Every push and every merge performed by the automation MUST
  authenticate with the dedicated fleet credential, never with the ephemeral
  workflow credential that suppresses downstream workflow runs.
- **FR-013**: The merge decision logic MUST be runnable and testable outside
  the scheduler with a preview mode that prints the selected PR and each gate
  result while performing no mutation.
- **FR-014**: Automated tests MUST cover the gate evaluation logic and the
  trailer parsing (area and release-note extraction and validation).

## Acceptance Criteria

- **AC-1**: Serialization is configured so at most one merge runs at a time
  and an in-flight run is never cancelled (covers FR-002).
- **AC-2**: The squash operation uses an explicit subject and trailer body and
  no merge-style or rebase-style merge is possible (covers FR-008).
- **AC-3**: Approval at the current head revision is evaluated, and a mismatch
  routes the PR back for review (covers FR-004, FR-007).
- **AC-4**: A red integration branch is undone with a revert that preserves
  lineage, and the resolved issue is reopened with the fix mark (covers
  FR-010, FR-011).
- **AC-5**: Issue closure after a squash names the squash commit on each
  resolved issue (covers FR-009).
- **AC-6**: No push or merge path in the automation authenticates with the
  ephemeral workflow credential (covers FR-012).
- **AC-7**: Preview mode against the live repository prints the PR it would
  select and each gate result with zero mutations (covers FR-013).
- **AC-8**: The gate-logic and trailer-parsing tests exist and pass (covers
  FR-004, FR-014).
- **AC-9**: Selection prefers the longest-waiting highest-priority
  ready-to-merge PR, else the longest-waiting ready-to-merge PR (covers
  FR-003).
- **AC-10**: Gate failures swap exactly the defined follow-up label and post
  exactly one comment naming the failed gate, except gate 1 which merges
  nothing and changes no mark (covers FR-005, FR-006).
- **AC-11**: The advisory approval gate is recorded but never blocks a merge
  on its own in the current stage (covers FR-007).
- **AC-12**: All four triggers (mark labelled, branch-verification completed,
  thirty-minute schedule from the default branch, manual) are configured
  (covers FR-001).

## Edge Cases

- Empty queue: a run with no ready-to-merge PR merges nothing and changes
  nothing.
- Gate 1 red or stale: no mark is changed and nothing merges; the next
  branch-verification completion retries.
- Highest-priority PR fails a gate: it is routed per its gate mapping and the
  run evaluates the next candidate rather than stopping.
- PR retargeted away from the integration branch mid-queue: gate 2 routes it
  back to its author for correction.
- Textual conflict appearing after selection: gate 3 routes the PR for
  rebasing; the run continues with the next candidate.
- Head revision moves after approval: the advisory gate records the mismatch
  without blocking; the follow-up review routing applies only when the gate
  becomes enforcing.
- PR description missing either trailer line, carrying an invalid area value,
  or carrying an empty release-note line: gate 6 routes the PR back to its
  author.
- Multiple resolved issues on one PR: every resolved issue is closed with the
  squash commit named; a revert reopens the resolved issues with the fix mark
  and run location.
- Flaky verification: exactly one retry runs before any revert; a green retry
  causes no revert.
- Two slices conflict semantically but merge cleanly: no gate catches it at
  merge time; branch verification plus the revert path own the recovery.
- Concurrent trigger delivery while a run is in flight: the second run waits
  rather than overlapping or cancelling the first.

## Out of Scope

- Promotion of verified work to later branches, release-notes generation,
  release-candidate tooling, and branch-guard rules.
- Changes to reviewer briefs, build briefs, PR template content, or branch
  verification triggers themselves (this automation consumes them).
- Batch merging with bisection, verification splitting for speed, hosted
  preview environments, cadence changes, and identity/enforcement upgrades.
- Backfill or retargeting of already-open PRs.

## Clarifications

- Q: On a gate failure, does the run stop or move to the next PR, given the
  description says "move on" while the gate table says gate 1 exits? -> A:
  Gate 1 exits with no mark changed (chosen by agent from the strategy
  document §4.3 gate-1 row); all other gates re-mark, comment once, and
  evaluate the next candidate (chosen by agent from the issue description and
  the gate table).
- Q: Does one scheduler run merge at most one PR, or drain the whole queue?
  -> A: At most one merge per run; gate failures skip to the next candidate
  within the same run, and a successful merge ends the run so branch
  verification for the new head completes first (chosen by agent from the
  strategy document throughput ceiling of one merge per verification run).
- Q: Which issues count as "linked" for close/reopen? -> A: Issues the PR
  resolves via its closing references (chosen by agent; the plan stage pins
  the exact reference source against the platform API).
- Q: Does the advisory approval gate change any mark when it mismatches? ->
  A: No mark change and no block in the current stage; the outcome is only
  recorded, and review routing applies when the gate becomes enforcing
  (chosen by agent from the strategy document §7).
