# Contributing

Setup, checks and boundaries are in [AGENTS.md](AGENTS.md).
Admission rules for changes are in [docs/product/ADMISSION.md](docs/product/ADMISSION.md).

## Branches

The branch model is in [docs/FLEET.md](docs/FLEET.md#branch-model).

- Pull requests target `dev`. They are squash-merged, one commit per PR.
- `dev` is merged into `staging` with a merge commit.
- `staging` is merged into `main` through a promotion PR.
- No one pushes directly to `dev`, `staging` or `main`.

## Commits

Use Conventional Commits: `type(scope): summary`, for example
`docs(agents): add area map` or `ci: gate fleet workflows behind FLEET_WORKFLOWS`.

## Pull requests

The PR body follows [.github/pull_request_template.md](.github/pull_request_template.md).
It must contain:

- exactly one `Area:` line with the value `api`, `web`, `db` or `infra`;
- exactly one `Release-note:` line, which an adopter reads to decide whether to take the change.

List any rename, move or deletion under `apps/` in the release note as `old/path → new/path`.

Dependabot PRs do not have the `Area:` and `Release-note:` lines. A person edits the PR
body to add them before the PR is merged.

## Release notes

`scripts/release-notes.sh BASE HEAD` builds the release-note list from the `Area:` and
`Release-note:` lines of the commits in a range. `make release-notes BASE=main HEAD=staging`
runs it. Released changes are recorded in [CHANGELOG.md](CHANGELOG.md).
