# Feature Specification: Fleet builds target dev, review stops merging

**Issue**: #1818  **Status**: Draft  **Areas**: (none — no area label; area context missing, see assumptions)

## User Scenarios and Testing

### User Story 1 - Build agents open work against the integration branch (Priority: P1)

As a fleet build agent, I want my working brief to tell me to branch from and open pull requests against the integration branch, so that approved changes land for integration instead of going straight to the default branch.

**Independent test**: Follow the build brief for a sample issue; confirm the opened pull request targets the integration branch without any lookup of the repository's default branch.

**Acceptance scenarios**:

1. Given the build brief, When an agent prepares a pull request, Then the request targets the integration branch and no step resolves the default branch.

### User Story 2 - Review agents approve without merging (Priority: P1)

As a review agent, I want the approval path to record my approval (review event, verdict, approved head commit) and hand the pull request to the merge queue, so that no agent merges code directly and every merge goes through the same deterministic gate.

**Independent test**: Simulate an approval on a non-high-risk pull request; confirm an approval review is submitted, the approval comment records the verdict and the approved head commit, the merge-queue trigger label is set, the claim is released, and no merge command runs.

**Acceptance scenarios**:

1. Given an approved non-high-risk pull request, When the review agent finishes approval, Then an approval review event exists for the approved head commit, the approval comment states the verdict and that commit, the pull request carries the merge-queue trigger label, the claim label is gone, and the pull request is not merged.
2. Given a high-risk pull request, When review completes, Then the existing human-gate path is used unchanged (owner merges).

### User Story 3 - Pull requests carry machine-readable release metadata (Priority: P1)

As the release-notes tooling, I want every pull request body to carry machine-readable area and release-note lines, so that slices can be grouped by area without human parsing.

**Independent test**: Open a pull request from the template and confirm both machine-read lines are present with an allowed area value and a one-line note.

**Acceptance scenarios**:

1. Given the pull request template, When a new pull request is created, Then the Release-note section contains an area line with one allowed value and a one-line release-note line.

### User Story 4 - Label contract reflects the merge queue (Priority: P1)

As a fleet operator, I want the label contract to describe the merge trigger label as "approved, waiting for the merge queue", so that briefs, label descriptions, and dispatcher configuration stay consistent.

**Independent test**: Read the label contract row for the merge trigger label and confirm it states the waiting-for-queue meaning.

**Acceptance scenarios**:

1. Given the label contract document, When its merge-trigger row is read, Then it states the label means approved and waiting for the merge queue.

## Requirements

- **FR-001**: The build brief MUST instruct agents to branch from the integration branch and open pull requests against it, and MUST NOT instruct any default-branch lookup.
- **FR-002**: The review approval path MUST submit an approval review event for the approved head commit.
- **FR-003**: The review approval comment MUST record the verdict line and the approved head commit.
- **FR-004**: The review approval path MUST set the merge-queue trigger label and MUST remove the claim label.
- **FR-005**: The review approval path MUST NOT merge the pull request under any condition.
- **FR-006**: The high-risk review path MUST remain unchanged (human merge decision via the needs-human label).
- **FR-007**: The pull request template MUST include machine-readable area and release-note lines in its Release-note section, with the area restricted to the four allowed values.
- **FR-008**: The label contract MUST describe the merge trigger label as approved and waiting for the merge queue.
- **FR-009**: The built pull request MUST carry the needs-human label and MUST NOT be merged before the merge-queue piece lands (sequencing gate imposed by the owner).

## Acceptance Criteria

- **AC-1**: Compliance check CICD-10 passes: the build brief references the integration branch as base and contains no default-branch lookup. (covers FR-001)
- **AC-2**: Compliance check CICD-11 passes: no agent brief merges a pull request. (covers FR-005)
- **AC-3**: Compliance check CICD-12 passes: the review brief sets the merge-queue trigger label and references the approved head commit. (covers FR-002, FR-003, FR-004)
- **AC-4**: Compliance check CICD-13 passes: the pull request template contains both machine-read lines. (covers FR-007)
- **AC-5**: The label-contract check from #1811 passes with the updated merge-trigger row. (covers FR-008)
- **AC-6**: A dry walk of the review brief's approval path on a sample non-high-risk pull request produces an approval review, a verdict-plus-commit comment, the trigger label set, the claim label removed, and no merge. (covers FR-002, FR-003, FR-004, FR-005)
- **AC-7**: A dry walk of the high-risk path still ends with the human merge decision and no agent merge. (covers FR-006)
- **AC-8**: The built pull request carries needs-human until the merge-queue piece is in place. (covers FR-009)

## Edge Cases

- A pull request spanning more than one area: the dominant area is used and the reason plus the other areas appear in the release-note line.
- New commits land after approval: the recorded head commit no longer matches, so the merge queue must treat the approval as stale (queue-side rule, not this piece).
- A pull request body with a missing or malformed area line: release-notes tooling cannot group it; the template default plus review scrutiny are the only guard in this piece.
- A pull request approved before this change lands keeps the old merge behaviour; only approvals after landing follow the new path.

## Out of Scope

- The merge queue itself (piece 5, #1817) and its squash, check, and auto-revert rules.
- CI trigger changes (piece 3, #1816) and promotion, branch-guard, and release-candidate tooling (pieces 4, 6, 7, 8).
- Retargeting already-open pull requests to the integration branch (piece 9) and autopilot prompt changes (piece 10).
- Creating the integration and staging branches and related settings (piece 1).
- Any product behaviour change; this piece touches fleet process files and the pull request template only.

## Clarifications

- No open scope points. Every behaviour is settled by the issue description, the owner sequencing comment, and the referenced CI-CD contract (§4.2) with its compliance checklist (CICD-10–13). Nothing required a human decision at spec time; the sequencing gate (FR-009 / AC-8) is recorded as a requirement, not a question.
