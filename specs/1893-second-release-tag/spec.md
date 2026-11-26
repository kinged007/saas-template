# Feature Specification: Second release tag carrying the update path

**Issue**: #1893  **Status**: Clarified  **Areas**: area:docs

## User Scenarios and Testing

### User Story 1 - Adopter updates from one release tag to the next (Priority: P1)

An adopter who seeded a project from the first release tag takes the new release by following the upgrade guide alone, with no extra instructions, so the milestone's tag-to-tag update guarantee can actually be exercised.

**Independent test**: seed a fresh copy from the previous tag, follow the upgrade guide's seed and update sections verbatim to take the new tag, then run the guide's four verification commands; each exits 0.

**Acceptance scenarios**:
1. Given a copy seeded from the previous tag, When the adopter follows the upgrade guide alone to merge the new tag, Then the merge completes and all four verification commands exit 0.
2. Given the update succeeds, When the adopter inspects the merged tree, Then the extension seams, the project branch of the migration history, and the template-paths manifest are present.

### User Story 2 - Adopter knows what each release seeds (Priority: P1)

An adopter choosing a seed version reads the changelog and the release notes and learns exactly which commit each tag gives them, so they can trust that the new tag carries the update-path work and know what the old tag contains.

**Independent test**: read the changelog entry and both releases' notes without any other context; state the seed commit of each tag and what the new release adds.

**Acceptance scenarios**:
1. Given the published changelog, When the adopter reads the new release entry, Then it is dated, covers the update-path work grouped so the touched areas are visible, and the previous tag's section is unchanged from what was published.
2. Given the release notes for both tags, When the adopter reads them, Then the notes state the fate of the first tag and name which commit a seed from each tag gets.

### User Story 3 - Release is cut where adopters pull (Priority: P1)

The maintainer publishes the new release on a commit that is an ancestor of the branch adopters pull, with a published release record for the new tag, so the documented seed-and-merge procedure works from the branch adopters actually use.

**Independent test**: verify ancestry of the new tag against the adopter branch and confirm a published release record exists for it.

**Acceptance scenarios**:
1. Given the new tag, When ancestry against the adopter branch is checked, Then the tag is confirmed as an ancestor of that branch.
2. Given the new tag, When the adopter looks for its release record, Then exactly one published release exists for it and its notes carry the per-tag seed-commit statement.

## Requirements

- **FR-001**: The release process MUST place the new tag on a commit that is an ancestor of the branch adopters pull; until the promotion pipeline lands, that branch is the integration branch and the release notes MUST say so.
- **FR-002**: The changelog MUST gain a dated entry for the new release covering the update-path work, leaving the previous tag's section exactly as published.
- **FR-003**: A published release record MUST exist for the new tag; the first tag MUST be left exactly as published, and the new release's notes MUST state that decision plus which commit a seed from each tag gets.
- **FR-004**: A copy seeded from the previous tag MUST reach the new tag by following the upgrade guide alone, with the guide's four verification commands each exiting 0, and the commands plus their exit codes MUST be pasted in a comment.
- **FR-005**: The change MUST carry one area line and one release-note line as the admission gate requires.
- **FR-006**: The new tag version SHOULD be v0.2.0 (new update-path capability on top of the first release, pre-1.0 minor).

## Acceptance Criteria

- **AC-1**: The new tag is an ancestor of the branch adopters pull (the integration branch until the promotion pipeline lands), shown by an ancestry check (covers FR-001).
- **AC-2**: The changelog has a dated new-release entry covering the update-path work and the previous tag's section is byte-identical to what was published (covers FR-002).
- **AC-3**: One published release record exists for the new tag and its notes state the first-tag decision plus the seed commit of each tag (covers FR-003).
- **AC-4**: A seeded copy takes the new tag using only the upgrade guide, all four verification commands exit 0, and the commands with exit codes are pasted in a comment (covers FR-004).
- **AC-5**: The change carries exactly one area line and one release-note line in the required form (covers FR-005).
- **AC-6**: The new tag carries the seven merged update-path slices (extension seams, project migration branch, template-paths manifest) — verified by the AC-4 seeded update, not by reading the tree directly (covers FR-001, FR-004).

## Edge Cases

- The first tag points at a commit outside the release history (diverged ancestry); the release notes must still let an adopter determine what each tag seeds.
- The previous changelog section is accidentally edited while adding the new entry; the acceptance check compares it against the published text.
- The QA run follows memory or extra steps instead of the guide alone; the pasted transcript must show the guide's procedure was the only input.
- The promotion pipeline lands mid-work and changes which branch adopters pull; the tag ancestry check is re-run against the new adopter branch.

## Out of Scope

- Building or landing the promotion pipeline itself (tracked separately and open).
- Changing the seed or update procedure in the upgrade guide; this item exercises it, not redesigns it.
- Setting a recurring release cadence or versioning policy beyond this one release.
- Rewriting or deleting any published history beyond the explicitly decided fate of the first tag.

## Clarifications

- Q: Which branch is the new tag cut from — the integration branch now, or the adopter branch after the promotion pipeline lands? -> A: Tag the integration branch head now and state in the release notes that adopters pull that branch until the first promotion lands; the milestone acceptance criterion is blocked on a second tag existing and the promotion item has no landing date. Chosen by person (repository owner, 2026-11-26).
- Q: Is the first tag re-pointed at its merged commit or left exactly as published? -> A: Left exactly as published; the release notes document which commit a seed from each tag gets. Re-pointing rewrites a published tag adopters may have pinned and needs a force-push; documenting is reversible. Chosen by person (repository owner, 2026-11-26). No conventions-decision entry is needed since this preserves the settled convention.
- Q: Which version number does the new tag take? -> A: v0.2.0 (new capability on a pre-1.0 line; patch would imply a fix-only release, which this is not). Chosen by agent as a non-blocking assumption; correct it if the maintainer wants otherwise.
