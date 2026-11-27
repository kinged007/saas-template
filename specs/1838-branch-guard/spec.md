# Feature Specification: Branch guard checks pushes to dev, staging and main

**Issue**: #1838  **Status**: Clarified  **Areas**: none (area context missing)

## User Scenarios and Testing

### User Story 1 - Malformed commit pushed directly to dev is caught (Priority: P1)

A contributor pushes commits directly to the integration branch, bypassing
the merge queue. The guard checks each new commit in the pushed range and
fails the run, opening or updating a `needs-human` issue that names the
offending commits and the rule they break, so the maintainer learns about
the violation within minutes and reverts it with a new commit.

**Independent test**: push one commit without the required trailer lines to
`dev`; observe a red run and a `needs-human` issue naming that commit.

**Acceptance scenarios**:

1. Given a push to `dev` whose range holds one single-parent commit without
   an `Area:` line, When the guard runs, Then the run fails and the
   resulting issue names that commit and the `dev` rule.
2. Given a push to `dev` whose range holds only single-parent commits that
   each carry both trailer lines, When the guard runs, Then the run passes
   and no new issue is opened.

### User Story 2 - Wrong-parent promotion to staging or main is caught (Priority: P1)

A contributor moves `staging` or `main` forward with a merge that did not
come from the previous stage (e.g. a merge of an untested branch into
`staging`, or of `dev` straight into `main`). The guard fails the run and
reports which merge commit has the wrong second parent, so promotions stay
strictly `dev` → `staging` → `main`.

**Independent test**: merge a non-`dev` branch into `staging` and push;
observe a red run naming that merge commit.

**Acceptance scenarios**:

1. Given a push to `staging` whose range holds a merge commit whose second
   parent is not a commit on `dev`, When the guard runs, Then the run fails
   and the issue names that merge commit.
2. Given a push to `main` whose range holds a merge commit whose second
   parent was not the `staging` head at merge time, When the guard runs,
   Then the run fails and the issue names that merge commit.
3. Given correct promotions (`dev` head into `staging`, `staging` head into
   `main`), When the guard runs, Then both runs pass.

### User Story 3 - Force push is caught and reported (Priority: P1)

A contributor rewrites history on a protected branch with a force push. The
guard fails the run even when every visible commit message looks well-formed,
and the issue identifies the push as a non-fast-forward, so history rewrites
are never silent.

**Independent test**: force-push a rewritten `dev` tip; observe a red run
whose issue says the push was a non-fast-forward.

**Acceptance scenarios**:

1. Given a force push to any of `dev`, `staging` or `main`, When the guard
   runs, Then the run fails and the issue identifies it as a
   non-fast-forward push.
2. Given a second consecutive violation on the same branch while the first
   issue is still open, When the guard runs, Then it updates the existing
   open issue instead of opening a duplicate.

## Requirements

- **FR-001**: The system MUST run the guard on every push to `dev`, `staging` and `main`.
- **FR-002**: The system MUST check every new first-parent commit in the pushed range on `dev`: each must be a single-parent commit whose message carries `Area:` and `Release-note:` lines, or a revert commit.
- **FR-003**: The system MUST check every new first-parent commit in the pushed range on `staging`: each must be a merge commit whose second parent is a commit on `dev`.
- **FR-004**: The system MUST check every new first-parent commit in the pushed range on `main`: each must be a merge commit whose second parent was the `staging` head at merge time.
- **FR-005**: The system MUST fail the run on any non-fast-forward (force) push to `dev`, `staging` or `main`, regardless of commit contents.
- **FR-006**: The system MUST check only the pushed range (the before-to-after interval of that push); commits already on the branch before the push are never flagged.
- **FR-007**: The system MUST, on any failure, leave the run red and open a `needs-human` issue, or update the still-open one for the same branch, naming the offending commits and the rule each broke.
- **FR-008**: The guard logic MUST live in a versioned check script covered by automated tests that build a throwaway fixture repository and exercise a good and a bad commit per branch plus a force push.
- **FR-009**: The change that introduces the guard MUST itself satisfy the `dev` rule (its squash message carries both trailer lines), and its PR MUST show one green guard run on `dev` after the merge, or document how the first run was verified.

## Acceptance Criteria

- **AC-1**: Pushing one trailer-less commit to `dev` produces a red run and a `needs-human` issue naming that commit (covers FR-001, FR-002, FR-007).
- **AC-2**: Pushing only well-formed single-parent commits to `dev` produces a green run and no new issue (covers FR-002).
- **AC-3**: Merging a branch other than `dev` into `staging` and pushing produces a red run naming the merge commit; merging the `dev` head produces a green run (covers FR-001, FR-003).
- **AC-4**: Merging anything other than the `staging` head into `main` and pushing produces a red run naming the merge commit; merging the `staging` head produces a green run (covers FR-001, FR-004).
- **AC-5**: A force push to any of the three branches produces a red run whose issue identifies it as a non-fast-forward (covers FR-005).
- **AC-6**: A push whose range contains no new commits beyond the two historic `dev` commits without trailer lines (`462dfea2d`, `2f1e27fd7`) produces a green run (covers FR-006).
- **AC-7**: Two consecutive violations on one branch with the first issue still open result in one updated issue, not two (covers FR-007).
- **AC-8**: The automated suite passes and includes, at minimum, a good and a bad fixture case per branch rule plus a force-push case (covers FR-008).
- **AC-9**: The `docs/FLEET.md` branch-guard coverage check passes: the workflow definition references all three branches (covers FR-001).
- **AC-10**: The introducing PR shows one green guard run on `dev` after its merge, or records the alternative first-run verification (covers FR-009).

## Edge Cases

- A push that deletes one of the three branches: there is no new range to check; the run fails because a missing protected branch breaks the branch model.
- A push whose before-to-after interval is empty or contains no first-parent commits: the run passes.
- A merge commit pushed to `dev`: it has more than one parent, so it fails the `dev` rule (the integration branch stays linear; the merge queue squash-merges).
- A `staging` merge whose second parent reached `dev` only after the merge: ancestry is evaluated against `dev` at check time, so ordering races resolve in favour of the branch state when the guard runs.
- `main` merges after `staging` has moved forward: the check accepts any second parent reachable from the current `staging` head, since exact at-the-time equality is unverifiable after the fact.
- The guard opens issues but never pushes or merges, so it authenticates with the default workflow credential; no long-lived personal credential is needed.
- Concurrent violating pushes to the same branch: issue updates are idempotent per branch, so interleaved runs converge on one open issue.

## Out of Scope

- Preventing bad pushes (branch rulesets / Stage 2 enforcement); the guard detects within minutes, it does not block.
- The product loop's periodic audit of the three branches against the same rules.
- Reverting a violating push; recovery stays a maintainer action with a new commit, never a force push.
- Changes to `ci.yml`, `e2e.yml`, the merge queue, promotion, release notes, or release-candidate tooling.
- Click-through verification or hosted preview environments.

## Clarifications

- Q: What does "a commit on `dev`" mean for the `staging` rule when `dev` keeps moving? -> A: The merge's second parent must be reachable from (an ancestor of) the `dev` head at the time the guard runs. Chosen by agent:spec as the only definition testable after the fact with standard history queries.
- Q: What does "the `staging` head at merge time" mean for the `main` rule once `staging` has moved on? -> A: The merge's second parent must be reachable from the current `staging` head. Chosen by agent:spec; exact at-the-time equality cannot be reconstructed later, and ancestry preserves the intent (nothing reached `main` without passing through `staging`).
- Q: How does open-or-update of the `needs-human` issue work? -> A: One open issue per branch, found by a guard-specific title prefix naming the branch; a run updates the open one with the new offending commits, rule, and run link, or creates it (labelled `needs-human`) when none is open. Chosen by agent:spec; no repo precedent exists for workflow-opened issues.
- Q: How are branch-deletion pushes handled? -> A: A push event that deletes `dev`, `staging` or `main` fails the run. Chosen by agent:spec; a missing protected branch breaks the branch model, and there is no range to check.
- Q: Which subjects count as a `revert:` commit on `dev`? -> A: Any subject with a revert marker: the `revert:` convention (case-insensitive) or the version-control tool's default revert subject for the commit being reverted. Chosen by agent:spec so the merge queue's own automatic reverts are not flagged by the guard.
