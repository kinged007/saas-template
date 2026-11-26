# Tasks — #1893 second release tag (v0.2.0)

Phases: Setup and facts first, Implementation, Polish. `[P]` = parallelisable
with neighbours (different files/refs, no dependency).

## Setup and facts first

- [ ] T001 [AC-1, AC-3] Workspace facts — `git fetch --tags`, record `git rev-parse dev`, `git tag --list "v*"`, `gh release list`, `git merge-base --is-ancestor v0.1.0 dev; echo $?`, and confirm whether #1880 has landed (adopter branch still `dev` vs new `main`).
- [ ] T002 [P] [AC-2] Published-baseline guard — save `sha256sum` of the current `## [0.1.0] - 2026-11-20` section of `CHANGELOG.md` so the edit can be proven byte-identical afterwards.
- [ ] T003 [P] [AC-4] QA readiness — confirm the four verify commands resolve to Makefile targets (`make db-check`, `make api-test`, `make web-build`, `make web-test`) and note their CI job counterparts in `.github/workflows/ci.yml`; prepare an empty scratch dir outside the worktree for the seeded copy.

## Implementation

- [ ] T004 [AC-2] `CHANGELOG.md` — add dated `## [0.2.0]` entry covering the seven update-path slices grouped by touched area, plus per-tag seed-commit note (`v0.1.0 → 779577e`; `v0.2.0 → <dev-head-sha>`) and adopter-branch note (`dev` until first promotion lands); leave `[0.1.0]` section untouched. Build the content from dev history of the seven slices, NOT from `git log v0.1.0..dev` (diverged base).
- [ ] T005 [AC-2] `CHANGELOG.md` guard — re-hash the `[0.1.0]` section and prove byte-identical to the T002 baseline.
- [ ] T006 [AC-1] Cut tag `v0.2.0` — annotated tag on `dev`'s head SHA recorded in T001; verify with `git merge-base --is-ancestor v0.2.0 dev` (or against `main` if #1880 landed mid-work per T001).
- [ ] T007 [AC-3] GitHub release for `v0.2.0` — exactly one published (non-draft) release; notes state `v0.1.0` left exactly as published, name the seed commit of each tag, and state adopters pull `dev` until the first promotion lands.
- [ ] T008 [AC-4, AC-6] Seeded-copy QA — in the scratch dir, seed from `v0.1.0` following `docs/UPGRADING.md` §1 verbatim, then take `v0.2.0` per §2 (one-time `--allow-unrelated-histories` first sync), observing extension seams, project Alembic branch, and `TEMPLATE_PATHS` manifest present after the merge.
- [ ] T009 [AC-4] Four verify commands in the seeded copy — run `make db-check`, `make api-test`, `make web-build`, `make web-test`, record each exit code, and paste commands + exit codes in an issue comment.

## Polish

- [ ] T010 [AC-5] Commit trailers — squash commit carries exactly one `Area: docs` line and one `Release-note:` line per `docs/product/ADMISSION.md` Gate 2 (no `apps/` renames, so no `old → new` list needed).
- [ ] T011 [AC-1, AC-3] Smoke test — `git merge-base --is-ancestor v0.2.0 dev && gh release view v0.2.0 --json tagName,isDraft` passes (ancestry true, published release).
- [ ] T012 [Polish] Quality gate for a docs/release change — `git status --short` shows only `CHANGELOG.md` staged intent (tag/release are refs, not files); run the repo's cheapest relevant check (`./scripts/check-label-contract.sh`, from CI) and confirm no code gate regressed.
