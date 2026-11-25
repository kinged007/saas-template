# Feature Specification: Protected-branch source guard

**Issue**: #1874  **Status**: Draft  **Areas**: none (no area label on the issue; area context missing)

## User Scenarios and Testing

### User Story 1 - Misdirected PR is rerouted automatically (Priority: P1)

A contributor opens a pull request targeting the protected branch from any branch other than the release-candidate branch. The system marks the required check as failed, reroutes the PR to target the integration branch, and leaves a single explanatory comment, so the change still flows through the normal pipeline without maintainer intervention.

**Independent test**: open a PR from a feature branch to the protected branch; verify the check fails, the PR now targets the integration branch, and exactly one guidance comment exists.

**Acceptance scenarios**:
1. Given a PR from a feature branch targeting the protected branch, When the guard evaluates it, Then the check fails and the PR is rerouted to the integration branch with one explanatory comment.
2. Given a PR from a fork targeting the protected branch, When the guard evaluates it, Then it is rerouted to the integration branch the same way, with a failed check.

### User Story 2 - Legitimate promotion passes untouched (Priority: P1)

The maintainer opens a promotion PR from the release-candidate branch into the protected branch. The system marks the check as passed and changes nothing about the PR.

**Independent test**: open a PR from the same-repository release-candidate branch to the protected branch; verify the check passes and no comment or retarget occurs.

**Acceptance scenarios**:
1. Given a PR whose head is the same-repository release-candidate branch targeting the protected branch, When the guard evaluates it, Then the check passes with no comment and no retarget.

### User Story 3 - Everyday PRs are unaffected (Priority: P2)

A contributor opens a PR targeting the integration branch or the release-candidate branch. The guard ignores it entirely.

**Independent test**: open PRs targeting the integration branch and the release-candidate branch; verify the guard takes no action on either.

**Acceptance scenarios**:
1. Given a PR whose base is the integration branch, When any guarded event occurs, Then the guard takes no action.
2. Given a PR whose base is the release-candidate branch, When any guarded event occurs, Then the guard takes no action.

### User Story 4 - Guard cannot be bypassed or weaponized (Priority: P1)

A PR targeting the protected branch contains malicious changes to the guard itself. The guard still runs its trusted logic, never executes the PR's code, and uses only the minimum privilege needed to retarget and comment.

**Independent test**: submit a PR that modifies the guard's own logic; verify the evaluation still uses the trusted version and passes or fails per the branch rules without running PR code.

**Acceptance scenarios**:
1. Given a PR targeting the protected branch that edits the guard, When the guard runs, Then it evaluates using the trusted base-branch version of the logic.
2. Given any PR evaluation, When the guard acts, Then it performs no checkout of the PR head and executes no PR-supplied code.

## Requirements

- **FR-001**: The system MUST evaluate every PR targeting the protected branch when it is opened, reopened, synchronized with new commits, or edited.
- **FR-002**: The system MUST report a passing check with no side effects when the PR head is the same-repository release-candidate branch.
- **FR-003**: The system MUST report a failing check, retarget the PR to the integration branch, and post exactly one explanatory comment (PRs merge into the integration branch; only the release-candidate branch merges into the protected branch) for any other head, including same-named branches from forks.
- **FR-004**: The system MUST take no action on PRs whose base is any branch other than the protected branch.
- **FR-005**: The system MUST evaluate using the trusted base-branch logic so a PR cannot alter the verdict on itself, and MUST NOT check out or execute PR-supplied code.
- **FR-006**: The system MUST expose its verdict as a named check that branch protection can require.
- **FR-007**: The system MUST ship with an offline self-test (stubbed forge CLI, no network) covering a feature-branch retarget with failed check, a release-candidate pass, ignored non-protected bases, and fork retarget; the self-test MUST run in the continuous-integration pipeline.
- **FR-008**: The branch-model documentation MUST state that only the release-candidate branch is merged into the protected branch and that the guard enforces it, and the compliance checklist MUST gain a matching item.

## Acceptance Criteria

- **AC-1**: A PR from a non-release-candidate head to the protected branch ends with a failed check, retargeted to the integration branch, and exactly one guidance comment (covers FR-001, FR-003).
- **AC-2**: A PR from the same-repository release-candidate branch to the protected branch shows a passed check with no comment and no retarget (covers FR-002).
- **AC-3**: PRs targeting the integration branch or the release-candidate branch trigger no guard action (covers FR-003 scope limit, FR-004).
- **AC-4**: A PR from a fork targeting the protected branch is retargeted to the integration branch with a failed check (covers FR-003).
- **AC-5**: A PR that edits the guard's own logic is still evaluated by the trusted version, and no evaluation checks out or runs PR code (covers FR-005).
- **AC-6**: The guard's verdict appears as a named check selectable as required in branch protection (covers FR-006).
- **AC-7**: The offline self-test passes locally and runs as part of the CI pipeline (covers FR-007).
- **AC-8**: The docs state the only-into-protected rule and the checklist contains the matching item (covers FR-008).

## Edge Cases

- A fork branch coincidentally named like the release-candidate branch is treated as an ordinary head and retargeted; only the same-repository release-candidate branch passes.
- Repeated events on an already-retargeted PR (its base is now the integration branch) are ignored; no second comment is posted.
- If the PR is merged or closed before the retarget lands, the run ends without leaving misleading state.
- The explanatory comment appears at most once per PR even if several guarded events fire before the retarget completes.

## Out of Scope

- The branch-protection settings themselves (selecting the check as required) — applied by the maintainer separately.
- Which credential performs the retarget and comment, beyond "one permitted to do both" — the plan stage chooses between the options the issue allows.
- Changes to the merge queue, the promotion flow, or any product behavior.

## Clarifications

- No blocking questions were raised. The description plus triage settled the candidate open points (credential either/or, comment-once behavior, rulesets out of scope), so the draft carries no `[NEEDS CLARIFICATION]` markers.
