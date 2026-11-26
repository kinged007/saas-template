# Plan — #1893 second release tag carrying the update path (v0.2.0)

Spec: `specs/1893-second-release-tag/spec.md` (Status: Clarified; both blocking
questions answered by the repository owner 2026-11-26; requirements taken from
the spec, not re-derived from the description).

Decisions carried forward (do not re-ask):
- Tag the integration-branch head (`dev`) now; release notes state adopters
  pull `dev` until the promotion pipeline (#1880, open, no landing date) lands.
- Leave `v0.1.0` exactly as published on `779577e`; document per-tag seed
  commits in `CHANGELOG.md` and the GitHub release. No `DECISIONS.md` entry
  (preserves the settled convention).
- Version number: `v0.2.0` (new capability on the pre-1.0 line).

## Approach

This is a release chore, not a code change. No files under `apps/` are
touched, so there are no migrations, no API contracts, and no UI to verify.
The work is: one `CHANGELOG.md` entry, one annotated tag on `dev`'s head, one
published GitHub release, and one end-to-end QA run that proves the milestone
criterion (seed from old tag → merge new tag via `docs/UPGRADING.md` alone).

Why this order: facts first (re-verify the description's tag/ancestry claims
in this workspace, which currently has no tags fetched and no `main` branch),
then the changelog edit with a byte-identical guard on the published
`[0.1.0]` section, then tag + release, then the seeded-copy QA that validates
everything. The QA run is the acceptance proof for AC-4 and AC-6; nothing is
proven by reading the tree directly.

Key pitfall the build must respect: `v0.1.0` is not an ancestor of `dev`
(diverged per the description), so `git log v0.1.0..dev` and
`scripts/release-notes.sh v0.1.0 dev` do not enumerate "what the release
adds". The changelog entry must be built from the integration-branch history
(the seven merged slices: PRs #1799, #1800, #1801, #1804, #1812, #1813, #1879,
grouped so the touched areas are visible), not from a tag range rooted at
`v0.1.0`.

## Files to change

- `CHANGELOG.md` — add a dated `## [0.2.0]` entry covering the update-path
  work (extension seams, project Alembic branch, `TEMPLATE_PATHS` manifest +
  path-check script, `UPGRADING.md` procedure), grouped so touched areas are
  visible; carry a seed-commit note per tag (`v0.1.0 → 779577e`,
  `v0.2.0 → <dev-head-sha>`); leave the `## [0.1.0] - 2026-11-20` section
  byte-identical. (Only tracked file that changes, plus the tag and the
  GitHub release object, which are not files.)
- No other repo file changes. In particular: no edit to `docs/UPGRADING.md`
  (this item exercises it, per spec Out of Scope), no `docs/product/DECISIONS.md`
  entry (decision preserves convention), no migration, no code.

## Data and contract changes

None. No public interfaces, schemas, persisted data, config keys, or
dependencies change. The public surface affected is release metadata only:
a new tag `v0.2.0`, a new `CHANGELOG.md` section, and a new GitHub release
record. `v0.1.0` (tag object and any existing record) is left untouched.

## Test plan

Tests to write first: none — there is no code to unit-test, and the repo has
no release-process test harness. The acceptance proof is the live QA run
below, executed exactly as an adopter would, with the transcript pasted in a
comment (FR-004/AC-4).

- AC-1: `git fetch --tags && git merge-base --is-ancestor v0.2.0 dev`
  (re-run against `main` if #1880 lands mid-work and changes the adopter
  branch). Tag must be annotated.
- AC-2: `diff`/`sha256sum` of the `## [0.1.0]` section before vs after the
  edit — must be byte-identical; new section has a date and covers the
  seven slices grouped by area.
- AC-3: `gh release view v0.2.0` shows exactly one published release; notes
  state `v0.1.0` left as published and name the seed commit of each tag.
- AC-4: fresh scratch dir (outside the worktree): seed from `v0.1.0` per
  `docs/UPGRADING.md` §1 verbatim, then §2 merge of `v0.2.0`, then the §3
  four commands, each exiting 0: `make db-check`, `make api-test`,
  `make web-build`, `make web-test`. Paste commands + exit codes in a comment.
  The merged tree must show the extension seams, the project migration
  branch, and the `TEMPLATE_PATHS` manifest (AC-6, observed through this run).
- AC-5: squash commit carries one `Area:` line and one `Release-note:` line
  per `docs/product/ADMISSION.md` Gate 2 (area `docs`; rename list `None` —
  no `apps/` rename in this change).
- AC-6: covered by the AC-4 run, not by a separate tree assertion.

Smoke test (smallest real run of the built artifact): after tag + release,
`git merge-base --is-ancestor v0.2.0 dev && gh release view v0.2.0 --json tagName,isDraft`
— ancestry true, one published (non-draft) release. This is the documented
seed-and-merge entry point an adopter uses; no server start or browser check
applies to a release-metadata change.

## Risks

- Tagging `dev` while `CI-CD.md` §2 names `main` as the adopter branch:
  mitigated by stating the branch clearly in `CHANGELOG.md` and the release
  notes; if #1880 lands mid-work, re-run the AC-1 ancestry check against the
  new adopter branch before publishing.
- `v0.1.0` divergence tempts a `v0.1.0..dev` range for the changelog — that
  range is meaningless on diverged history and would produce a wrong entry;
  build the entry from the dev history of the seven slices instead.
- QA cost: the four verify commands need API deps (`uv sync`) and web deps
  (`npm ci`) in a scratch copy; on a cold cache this is the long pole of the
  item. No way around it — it is the acceptance proof.
- No local tags / no `main` in this workspace at plan time: the build must
  `git fetch --tags` and resolve `origin/dev` (and `origin/main` if #1880
  lands) rather than assuming local refs exist.
- Publishing is one-way in practice: a published tag/release cannot be
  quietly fixed. Double-check SHA, date, and notes before `gh release create`.

## Rollback

Before publishing: `git tag -d v0.2.0` locally (and `git push origin :v0.2.0`
only if the tag was pushed in error and no adopter could have pinned it yet)
plus `git revert` of the changelog commit. After publishing: do not delete or
move the tag or release — publish a follow-up `v0.2.1` correction instead.
`v0.1.0` is never touched under any circumstance.
