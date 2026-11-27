# CI

This page lists what each GitHub Actions workflow runs and how to run each check locally.
Run every command from the repository root.

The fleet workflows (merge queue, branch guard, source guard) and their jobs in `ci.yml`
are documented in [docs/FLEET.md](../FLEET.md). They run only when the repository variable
`FLEET_WORKFLOWS` is `true`.

## Workflows

| Workflow | Trigger | Runs |
|---|---|---|
| `ci.yml` | push to `dev`, `staging`, `main`; PR into `dev` or `main`; called by another workflow with a `sha` input | the jobs below |
| `e2e.yml` | push to `main`; PR into `main`; manual dispatch; called with a `sha` input | `web-e2e` |
| `merge-queue.yml`, `branch-guard.yml`, `source-guard.yml` | see [docs/FLEET.md](../FLEET.md) | fleet checks |

## Checks in `ci.yml` and `e2e.yml`

| Check | What it verifies | Run locally |
|---|---|---|
| `api-lint` | Ruff lint and format in `apps/api` | `make api-lint` |
| `api-test` | pytest in `apps/api` | `make api-test` |
| `db-check` | one migration head per chain; models match migrations | `make db-check` |
| `template-paths` | in a repository created from the template, lists template-owned files changed since the last template sync (advisory); in the template repository, runs the script self-test | `bash scripts/check-template-paths.test.sh` (template repository); `bash scripts/check-template-paths.sh` (derived repository, needs the `template` remote and its tags, see [UPGRADING.md](../UPGRADING.md)) |
| `web-build` | type-check and production build of `apps/web` | `make web-build` |
| `web-test` | `node --test` in `apps/web`, with at least one test discovered | `make web-test` |
| `web-e2e` (also `e2e.yml`) | Playwright suite in `apps/web` | `make web-test-e2e` |
| `trailing-newline` | every tracked `*.ts`, `*.tsx`, `*.py`, `*.sh` and `*.md` file ends with a newline | `git ls-files -z '*.ts' '*.tsx' '*.py' '*.sh' '*.md' \| while IFS= read -r -d '' f; do [ -s "$f" ] && [ -n "$(tail -c1 "$f")" ] && echo "$f"; done` prints nothing |
| `branch-guard-test` (fleet) | self-test of `scripts/branch-guard.sh` | `bash scripts/branch-guard.test.sh` |
| `label-contract` (fleet) | `.agents/` labels match [docs/FLEET.md](../FLEET.md) | `make label-contract` |
| `release-notes` (fleet) | self-test of `scripts/release-notes.sh` | `bash scripts/release-notes.test.sh` |
| `source-guard-test` (fleet) | self-test of `scripts/source-guard.sh` | `bash scripts/source-guard.test.sh` |

`web-build`, `web-test` and `web-e2e` are the three legs of one matrix job named `web`.
`web-e2e` uploads its Playwright report as an artifact when it fails.
