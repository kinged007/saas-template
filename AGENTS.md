# saas-template

## What it is

A multi-tenant B2B SaaS template, organised as a monorepo. `apps/api` is a FastAPI backend with SQLAlchemy and Alembic, managed with uv. `apps/web` is a Refine v5 frontend with shadcn/ui, managed with npm. See `README.md` for the feature list and `docs/ARCHITECTURE.md` for the design.

## Setup

Run all commands from the repository root.

- Python: use `uv`, not pip. Python 3.12 (`apps/api/.python-version`, `.github/workflows/ci.yml`).
- Web: use `npm`, not pnpm or yarn. Node 24 (`apps/web/.nvmrc`, `.github/workflows/ci.yml`).
- Web unit tests use `node --test`, not vitest or jest.
- Copy `apps/api/.env.example` to `apps/api/.env` and `apps/web/.env.example` to `apps/web/.env` (`README.md`).
- `make setup` installs uv and Node if missing. `make api-install` and `make web-install` install dependencies (`Makefile`).

## How to run checks

| Stage | Command |
|---|---|
| API lint and format | `make api-lint` |
| API type check | none |
| API tests | `make api-test` |
| Migrations | `make db-check` |
| Web type check and build | `make web-build` |
| Web unit tests | `make web-test` |
| Web lint | none |

Optional or slower:

- `make web-test-e2e` runs the Playwright suite. CI runs it as `web-e2e` (`docs/architecture/CI-CD.md`).
- `make api-test-nats` runs the real-NATS integration test. It starts NATS with docker (`make nats-up`).

Smoke test of the API without docker or embedded Postgres:

```bash
USE_SQLITE=1 make api-migrate
USE_SQLITE=1 make api API_PORT=8011   # in a second terminal
curl http://localhost:8011/api/v1/healthz   # {"status":"ok","service":"saas-template-api"}
```

Stop the API with Ctrl-C in its terminal.

## Single test

```bash
cd apps/api && uv run --extra dev pytest tests/test_auth.py::test_login_wrong_password -q
cd apps/web && node --test src/hooks/query-keys.test.ts
```

## Boundaries

Allowed without asking:

- Code and tests under `apps/`.
- Documentation.

A person must approve:

- `apps/api/alembic/versions/**` and `apps/api/alembic/project_versions/**`.
- `apps/api/src/core/security/**`.
- `infra/**`.
- `.github/workflows/**`.
- `scripts/db-*.sh`.
- Adding or upgrading a dependency.

Never:

- Commit `.env` files or secrets.
- Edit generated `.codesight/` files.
- Edit `node_modules` or `.venv`.

Admission rules for changes are in `docs/product/ADMISSION.md`.

## Process

Fleet labels: `docs/FLEET.md` is the single source for every `agent:*` label — read it before adding, removing, or renaming one.

Template admission rules: `docs/product/ADMISSION.md`. Optional fleet workflows: `docs/FLEET.md`.

## Enforced rules

"Fleet" rows run only when the repository variable `FLEET_WORKFLOWS` is `true` (`docs/FLEET.md`, Opt in).

| Rule | Check | Active |
|---|---|---|
| API lint and format (`ruff check`, `ruff format --check`) | `api-lint` | always |
| API tests pass | `api-test` | always |
| One template head and one project head; models match migrations; check-constraint names | `db-check` | always |
| Web type check and build | `web-build` | always |
| Web unit tests run and pass | `web-test` | always |
| Web end-to-end tests pass | `web-e2e`, `e2e` | always |
| Template-owned files changed (advisory in derived projects; script self-test in the template repository) | `template-paths` | always |
| Tracked `.ts`, `.tsx`, `.py`, `.sh` and `.md` files end with a newline | `trailing-newline` | always |
| A PR body has one `Area:` line with the value api, web, db or infra | `merge_queue.py` (gate 6) | fleet |
| A commit on `dev` has one valid `Area:` line and a `Release-note:` line, or is a revert | `branch-guard` | fleet |
| Branch model: `dev` takes single-parent commits, `staging` takes merges of `dev`, `main` takes merges of `staging` | `branch-guard` | fleet |
| A PR into `main` comes from the same-repository `staging` branch | `source-guard` | fleet |
| Fleet labels used in `.agents/` are documented in `docs/FLEET.md` | `label-contract` | fleet |
| The `branch-guard`, `source-guard` and release-notes scripts pass their self-tests | `branch-guard-test`, `source-guard-test`, `release-notes` | fleet |
| 14-digit migration ids, renames listed in the release note, `CONV-*` IDs, admission verdict | review only | n/a |

## Architecture conventions

`docs/architecture/CONVENTIONS.md` holds the normative rules (events, API, auth, data, web, config), each with an ID `CONV-<AREA>-NN` and a check. Build agents list the IDs a change touches in the plan; reviewers give a verdict per ID. A deviation needs an entry in `docs/product/DECISIONS.md`.

## Dev stack ports

`make dev` runs api on :8000 and web on :5173 by default. If those ports are
taken (e.g. another checkout's dev server), override them for that run:

```bash
USE_SQLITE=1 make dev API_PORT=8010 WEB_PORT=5273   # open http://localhost:5273
```

`API_PORT` / `WEB_PORT` also work on `make api` and `make web`. `scripts/dev.py`
passes the chosen web origin to the API as `CORS_ORIGINS` / `FRONTEND_URL` (the
default :5173 stays allowed), and `apps/web/vite.config.ts` proxies `/api/` and
`/ws` to `API_PORT`. No other port configuration is needed. The allowlisted dev
origin is the web origin on both loopback names (`localhost` and `127.0.0.1`,
since vite serves both) — open either and the session holds.

## Migrations

Models are the source of truth; migrations are generated, reviewed, committed.
After changing any model, generate the migration (`make db-new` assigns a
14-digit UTC timestamp revision id per `docs/product/DECISIONS.md` D-04):

```bash
make db-new m="acme orders"   # → 20261118104500_acme_orders.py
```

Review the diff (watch for accidental drops, wrong nullability, missing server_default),
commit the file.
`make db-check` (also in CI) fails on multiple heads or models≠migrations.
Full workflow: `docs/MIGRATIONS.md`.

---

## Frontend

**Skill:** `refine-dev` (itechmeat-llm-code-refine-dev) is at `.agents/skills/itechmeat-llm-code-refine-dev/SKILL.md` in the repo (`.claude/skills` is a symlink to `.agents/skills`). Load it for Refine.dev API details, but the rules in `docs/architecture/CONVENTIONS.md` and existing repo patterns take precedence over the skill's generic guidance (e.g. it assumes Mantine; this repo uses shadcn/ui).

**Stack (apps/web):** Refine **v5** (`@refinedev/core`, `@refinedev/react-router`) + custom `dataProvider` (wraps `@refinedev/simple-rest`) + `accessControlProvider` + sonner `notificationProvider`. shadcn/ui components in `src/components/ui/`; refine primitives (views, buttons, layout) in `src/components/refine-ui/`. Forms use `@refinedev/react-hook-form` + `react-hook-form` + `zod` + `@hookform/resolvers`.

**Refine rules and known non-compliant pages:** `docs/architecture/CONVENTIONS.md`, area FE (`CONV-FE-*`), access control (`CONV-AUTH-05`) and Known deviations.

**Dev notes:** Vite's proxy rule is `"/api/"` (trailing slash) — a bare `"/api"` prefix would also swallow SPA routes like `/api-keys` and `/api-keys/create`, forwarding them to the backend as 404s on hard refresh. Frontend validation: `npm run build` (runs `tsc --noEmit` first) and `npm test` (`node --test`, stdlib only). Testable logic lives in a plain `.ts` module — `node --test` cannot load `.tsx` or resolve the `@/` alias, so its runtime imports are relative with the `.ts` extension (`../lib/role-cap.ts`); share types with `import type`, which type stripping erases and which may use `@/` (CONV-FE-07). CI runs both (`web-build`, `web-test` jobs) on Node 24. No web lint script.
