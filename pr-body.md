## What and why

AGENTS.md states project facts and the enforced rules for any adopter. Template-contributor rules are replaced by one pointer to `docs/product/ADMISSION.md` and `docs/FLEET.md`. The PR template keeps the `Area:` and `Release-note:` fields and replaces the admission checklist with one verdict line.

Area: infra
Release-note: AGENTS.md lists the enforced rules with their CI checks; the PR template no longer carries the admission checklist.

Stacked on #1891: this branch is based on `agent/mun-54-pr2-fleet-docs` (its AGENTS.md and template hunks conflict with this change otherwise). Links to `docs/FLEET.md` resolve once #1891 merges. The PR base is `dev`.

## Files changed

- `AGENTS.md`: `Process` section (one pointer line) and `Enforced rules` table; contributor rules and the `agent:` label line removed.
- `.github/pull_request_template.md`: rule line beside `Area:`/`Release-note:`; one `Admission verdict (template repo only)` line with a relative link.

## Table verification (against workflow and script source)

- `api-lint`: `ruff check` and `ruff format --check` in `ci.yml`. Verified.
- `api-test`, `web-build`, `web-test`, `web-e2e`/`e2e`, `template-paths`: rows added; verified in `ci.yml` and `e2e.yml`.
- `db-check`: exactly two heads (template, project), empty autogenerate, constraint names. Verified.
- `trailing-newline`: covers tracked `*.ts`, `*.tsx`, `*.py`, `*.sh`, `*.md` only. Row states this.
- Area/Release-note row: split in two. `merge_queue.py` gate 6 checks only a valid single `Area:`; a missing or repeated `Release-note:` never blocks (title fallback). `branch-guard` checks one valid `Area:` and at least one `Release-note:` per `dev` commit; it does not check for exactly one.
- Branch model row: `branch-guard` verified for `dev`, `staging`, `main`. `source-guard` verified (separate row).
- Fleet label row: `check-label-contract.sh` verified. Worded as "fleet labels" to avoid the literal `agent:`.
- Self-test jobs (`branch-guard-test`, `source-guard-test`, `release-notes`): row added.
- Review-only row: no script checks 14-digit ids, `CONV-*` or the verdict (grep found none).

## Checks

- Trailing newline on both files: pass.
- `make label-contract`: pass.
- `bash scripts/*.test.sh` (4 scripts): pass.
- `python3 scripts/test_merge_queue.py`: pass.
- `merge_queue.parse_trailers` on the new template: area `api`, note parsed, no errors. The `branch-guard` Area and Release-note greps each match exactly one line.
- No `multica` in changed files. No `agent:` or `FLEET_TOKEN` in changed files.
- Relative link `../docs/product/ADMISSION.md` resolves.

## Not verified

- `FLEET_WORKFLOWS` gating takes effect only when #1888 merges; the table assumes it.
- CI on GitHub not run.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
