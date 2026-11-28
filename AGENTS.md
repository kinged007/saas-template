# saas-template — Project Context

**Stack:** fastapi | sqlalchemy | typescript
**Monorepo:** api, saas-template-web

26 routes | 10 models | 17 env vars | 247 import links

**API areas:** , /effective-permissions, /{api_key_id}, /register, /login, /refresh, /logout, /me, /{invitation_id}, /accept

**High-impact files** (change carefully):
- apps/api/src/db/session.py (imported by 17 files)
- apps/api/src/models/workspace.py (imported by 13 files)
- apps/web/src/types.ts (imported by 12 files)
- apps/api/src/settings.py (imported by 9 files)
- apps/api/src/services/workspaces.py (imported by 9 files)

**Required env vars:** DATABASE_URL

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

## Cookie `Secure` precedence

`cookie_secure_for()` (`apps/api/src/core/security/cookies.py`) decides the
refresh-cookie `Secure` flag. When it or `REFRESH_COOKIE_SECURE` changes,
restate the precedence identically in all three places, override first:
`apps/api/.env.example` (`REFRESH_COOKIE_SECURE` comment), `docs/ARCHITECTURE.md`
§5 auth flows table, and `docs/ARCHITECTURE.md` §9 security list. Behavior is
covered by `apps/api/tests/test_auth_cookie.py`; no doc-lint exists yet — add
one only if the wording drifts again.

---

## Frontend

**Skill:** `refine-dev` (itechmeat-llm-code-refine-dev) is installed for opencode (`~/.agents/skills/itechmeat-llm-code-refine-dev/SKILL.md`) and Claude Code (`.claude/skills/itechmeat-llm-code-refine-dev/SKILL.md`). Load it for Refine.dev API details, but the rules in `docs/architecture/CONVENTIONS.md` and existing repo patterns take precedence over the skill's generic guidance (e.g. it assumes Mantine; this repo uses shadcn/ui).

**Stack (apps/web):** Refine **v5** (`@refinedev/core`, `@refinedev/react-router`) + custom `dataProvider` (wraps `@refinedev/simple-rest`) + `accessControlProvider` + sonner `notificationProvider`. shadcn/ui components in `src/components/ui/`; refine primitives (views, buttons, layout) in `src/components/refine-ui/`. Forms use `@refinedev/react-hook-form` + `react-hook-form` + `zod` + `@hookform/resolvers`.

**Refine rules and known non-compliant pages:** `docs/architecture/CONVENTIONS.md`, area FE (`CONV-FE-*`), access control (`CONV-AUTH-05`) and Known deviations.

**Dev notes:** Vite's proxy rule is `"/api/"` (trailing slash) — a bare `"/api"` prefix would also swallow SPA routes like `/api-keys` and `/api-keys/create`, forwarding them to the backend as 404s on hard refresh. Frontend validation: `npm run build` (runs `tsc --noEmit` first) and `npm test` (`node --test`, stdlib only). Testable logic lives in a plain `.ts` module — `node --test` cannot load `.tsx` or resolve the `@/` alias, so its runtime imports are relative with the `.ts` extension (`../lib/role-cap.ts`); share types with `import type`, which type stripping erases and which may use `@/` (CONV-FE-07). CI runs both (`web-build`, `web-test` jobs) on Node 24. No web lint script.
