# Feature Specification: Promotion moves verified dev head to staging with main promotion PR

**Issue**: #1873  **Status**: Clarified  **Areas**: area:config

## User Scenarios and Testing

### User Story 1 - Daily promotion carries verified work toward release (Priority: P1)

Each morning the promotion runs on its own: it freezes the current head of the
integration branch, verifies that exact commit through the full integration
check suite and the end-to-end suite, and only then merges it into the release
candidate branch. It then opens (or refreshes) the single promotion pull
request from the candidate branch to the adopter-facing branch, with release
notes generated from the changes since the last release, so the maintainer
reviews one promotion per cadence instead of one pull request per change.

**Independent test**: advance the integration branch past the candidate branch
with all checks green and run the promotion; observe the candidate branch move
to the frozen commit and a promotion pull request appear (or update) with a
fresh release-notes body.

**Acceptance scenarios**:
1. Given the integration branch head is not yet contained in the candidate
   branch and both suites pass for that exact commit, When the scheduled run
   executes, Then the candidate branch advances to that commit via a merge
   commit and the promotion pull request exists with a regenerated body.
2. Given a promotion pull request was left unmerged and a newer verified
   commit arrives, When the promotion runs, Then no second pull request is
   opened; the existing one's body is regenerated to cover all new content.

### User Story 2 - Urgent fix is expedited without waiting for the schedule (Priority: P1)

A security fix or a broken adopter-facing branch cannot wait for the next
daily run. An authorized operator triggers the same promotion immediately by
hand; it verifies and moves the whole current integration head (never a
cherry-pick), so the candidate and adopter branches never diverge from the
integration branch.

**Independent test**: with a green fix merged to the integration branch,
trigger the promotion manually; observe the same outcome as the scheduled run
without waiting for the cron time.

**Acceptance scenarios**:
1. Given a green integration head newer than the candidate branch, When the
   promotion is triggered manually, Then it freezes, verifies, merges, and
   opens or updates the promotion pull request exactly as the scheduled run
   would.
2. Given the expedited run, When it completes, Then no commit bypasses the
   integration branch and no change lands directly on the adopter branch.

### User Story 3 - Failed verification blocks promotion and notifies the loop (Priority: P1)

Verification exists so unverified work never becomes a release candidate. When
either suite is red for the frozen commit, the promotion touches nothing:
the candidate branch stays where it was, no promotion pull request changes
are made for that commit, and a single blocked-promotion issue (created once,
updated thereafter) records the failing runs for the product loop to act on.

**Independent test**: force either suite to fail for the frozen commit and run
the promotion; observe the candidate branch unchanged and exactly one
blocked-promotion issue referencing the failed runs.

**Acceptance scenarios**:
1. Given the integration suite fails for the frozen commit, When the
   promotion runs, Then the candidate branch is not moved and a
   blocked-promotion issue naming that commit and the failed runs exists.
2. Given the end-to-end suite fails for the frozen commit, When the promotion
   runs, Then the same blocking outcome occurs as for an integration failure.
3. Given a blocked-promotion issue already exists from an earlier run, When a
   later run also fails, Then the existing issue is updated rather than
   duplicated.

### User Story 4 - Quiet days do nothing (Priority: P2)

On days when no new work landed, the promotion must be a silent no-op: no
merge, no pull request churn, no notification noise.

**Independent test**: run the promotion when the candidate branch already
contains the integration head; observe a clean exit with no push, no pull
request change, and no issue.

**Acceptance scenarios**:
1. Given the candidate branch already contains the frozen integration head,
   When the promotion runs, Then it exits successfully without pushing,
   opening, or updating anything.

### User Story 5 - Secrets and branch safeguards hold under automation (Priority: P1)

All pushes and pull request operations authenticate with the dedicated fleet
secret, never the default token (whose events would not trigger downstream
checks, silently faking verification). The adopter-facing branch is never
pushed to by automation; it moves only when the maintainer merges the
promotion pull request.

**Independent test**: inspect the promotion configuration and run the
self-test; observe no default-token usage for pushes or pull requests and no
step capable of writing to the adopter branch.

**Acceptance scenarios**:
1. Given the promotion configuration, When scanned for credential usage on
   any push or pull request operation, Then every such operation uses the
   fleet secret and none uses the default token.
2. Given any promotion run outcome (green, red, or no-op), When it finishes,
   Then the adopter-facing branch ref is unchanged by automation.

### User Story 6 - Promotion logic is self-tested in continuous integration (Priority: P2)

The freeze/verify/move/notify logic is exercised by a hermetic self-test that
stubs external service calls (same pattern as the existing branch-guard
self-test) and runs as part of the integration suite, so regressions in the
promotion logic fail the build before merge.

**Independent test**: run the self-test script locally with no network; observe
it passing, covering at least the green path, the red path, and the no-op
path.

**Acceptance scenarios**:
1. Given a clean checkout with stubbed external calls, When the self-test
   runs, Then it passes without network access and covers the green, red,
   and no-op outcomes.
2. Given a push that changes the promotion, When the integration suite runs,
   Then the self-test executes as one of its steps.

## Requirements

- **FR-001**: The system MUST run the promotion daily at 04:00 UTC and also
  allow an authorized manual trigger that runs the identical pipeline.
- **FR-002**: The system MUST freeze a single integration-branch commit at the
  start of a run and verify that exact commit (not a moving branch tip)
  through both the integration suite and the end-to-end suite before moving
  anything.
- **FR-003**: The system MUST order execution so the step that advances the
  candidate branch runs only after both verification suites report green for
  the frozen commit.
- **FR-004**: The system MUST, on green verification, advance the candidate
  branch to the frozen commit with a merge commit and open the candidate to
  adopter-branch promotion pull request, or regenerate the body of the already
  open one, with release notes covering everything since the adopter branch.
- **FR-005**: The system MUST include the frozen commit identity and both
  verification run references in the promotion pull request body alongside the
  release notes.
- **FR-006**: The system MUST, on red verification, leave the candidate branch
  untouched and open or update exactly one blocked-promotion issue naming the
  frozen commit and linking the failed runs, routed to the product loop.
- **FR-007**: The system MUST exit without any push, pull request change, or
  issue when the candidate branch already contains the frozen commit.
- **FR-008**: The system MUST perform every push and every pull request
  operation with the dedicated fleet secret and MUST NOT use the default token
  for any of them.
- **FR-009**: The system MUST NEVER push to the adopter-facing branch in any
  outcome; that branch moves only via the maintainer merging the promotion
  pull request.
- **FR-010**: The system MUST ship a hermetic self-test (stubbed external
  calls, no network) covering the green, red, and no-op paths, executed as a
  step of the integration suite.

## Acceptance Criteria

- **AC-1**: The promotion exposes both a daily 04:00 UTC schedule trigger and
  a manual trigger for the same pipeline (covers FR-001).
- **AC-2**: The step that advances the candidate branch declares dependencies
  on the integration-suite and end-to-end-suite invocations for the frozen
  commit, and both invoked suites check out the frozen commit identity rather
  than a branch tip (covers FR-002, FR-003).
- **AC-3**: On a green run with new commits, the candidate branch advances to
  the frozen commit via a merge commit and exactly one promotion pull request
  from candidate to adopter branch exists with a freshly generated body
  (covers FR-004).
- **AC-4**: The promotion pull request body names the frozen commit, links both
  verification runs, and contains the generated release-notes section
  (covers FR-005).
- **AC-5**: On a red run, the candidate branch ref is unchanged, no promotion
  pull request body is advanced for that commit, and exactly one
  blocked-promotion issue names the frozen commit with the failed run links
  (covers FR-006).
- **AC-6**: On a run where the candidate branch already contains the frozen
  commit, no push, pull request, or issue operation occurs and the run
  succeeds (covers FR-007).
- **AC-7**: No push or pull request operation in the promotion configuration
  uses the default token; all use the fleet secret (covers FR-008).
- **AC-8**: No step in the promotion configuration writes to the
  adopter-facing branch under any outcome (covers FR-009).
- **AC-9**: The hermetic self-test passes without network access, covers
  green, red, and no-op paths, and runs as a step of the integration suite
  (covers FR-010).

## Edge Cases

- A newer commit lands on the integration branch after the freeze: it waits
  for the next promotion; the running promotion verifies and moves only the
  frozen commit.
- A promotion pull request left unmerged across several runs: later runs keep
  updating its body rather than opening duplicates; its size grows until the
  maintainer merges it.
- Flaky suite failure: the run is treated as red (no promotion); rerunning
  the manual trigger re-verifies the new head rather than retrying
  mid-flight.
- Concurrent scheduled and manual runs overlapping: execution is serialized
  so only one freeze-move sequence is in flight at a time.
- Release-notes generation yielding an empty slice list (e.g. only reverts):
  the promotion pull request still opens or updates with the frozen commit
  identity and run links.
- The fleet secret is expired or missing: push and pull request operations
  fail closed; nothing moves and the failure is visible in the run logs
  rather than silently passing.

## Out of Scope

- Merging the promotion pull request into the adopter branch (a maintainer
  judgement step, done by hand with a merge commit).
- Tagging releases or publishing release artifacts from a promotion.
- Reverting a slice that fails maintainer click-through (handled on the
  integration branch through the normal pipeline; the next promotion carries
  the revert).
- Branch protection rulesets and enforcement hardening (a separate
  enforcement stage once the repository can enforce them).
- Changing the default branch to the adopter branch (a maintainer sequencing
  action after the first promotion carries the pipeline there).

## Clarifications

- Q: Which branch does the promotion workflow first land on, given the design
  doc says it lives on the default branch while the default is still the
  integration branch? -> A: It lands on the integration branch first, per the
  issue sequencing note; the schedule trigger starts firing because that
  branch is the current default, and the first manual promotion carries the
  workflow to the adopter branch before the default is switched. (chosen by
  agent from the issue body, which overrides the doc's assumption)
- Q: Which label routes the blocked-promotion issue to the product loop? ->
  A: The loop-triage label defined in the design doc's promotion section
  (chosen by agent from docs/architecture/CI-CD.md §4.5 step 3).
- Q: Does the promotion verify the frozen commit or the branch tip? -> A: The
  frozen commit: both invoked suites check out the pinned commit identity in
  every job, so a passing run always proves the exact commit that is moved
  (chosen by agent from docs/architecture/CI-CD.md §4.5 step 2).
