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

Fleet labels: `docs/FLEET_LABELS.md` is the single source for every `agent:*` label — read it before adding, removing, or renaming one.

## Product direction — read before proposing or building anything

Before opening an issue or PR that adds or changes behaviour, read
`docs/product/VISION.md` and apply `docs/product/ADMISSION.md`. Fill in the admission
section of the PR template; a PR without a verdict line is not ready for review.

Build only work that belongs to a started milestone (`docs/product/ADMISSION.md` Gate 0),
security fixes, and fixes that restore documented behaviour. Assess anything else and leave
it deferred — do not implement it.

Never:
- add hook, plugin or override layers over template files (`docs/product/DECISIONS.md` D-03);
- rename, move or delete a file under `apps/` without listing it in the PR's release-note
  line as `old/path → new/path` or `removed`;
- create a migration without a 14-digit timestamp revision id (D-04; see Migrations below; the squashed 0001 baseline is the only exception);
- add credits, branding or promotional text.

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

**Skill:** `refine-dev` (itechmeat-llm-code-refine-dev) is installed for opencode (`~/.agents/skills/itechmeat-llm-code-refine-dev/SKILL.md`) and Claude Code (`.claude/skills/itechmeat-llm-code-refine-dev/SKILL.md`). Load it for Refine.dev API details, but the rules in `docs/architecture/CONVENTIONS.md` and existing repo patterns take precedence over the skill's generic guidance (e.g. it assumes Mantine; this repo uses shadcn/ui).

**Stack (apps/web):** Refine **v5** (`@refinedev/core`, `@refinedev/react-router`) + custom `dataProvider` (wraps `@refinedev/simple-rest`) + `accessControlProvider` + sonner `notificationProvider`. shadcn/ui components in `src/components/ui/`; refine primitives (views, buttons, layout) in `src/components/refine-ui/`. Forms use `@refinedev/react-hook-form` + `react-hook-form` + `zod` + `@hookform/resolvers`.

**Refine rules and known non-compliant pages:** `docs/architecture/CONVENTIONS.md`, area FE (`CONV-FE-*`), access control (`CONV-AUTH-05`) and Known deviations.

**Dev notes:** Vite's proxy rule is `"/api/"` (trailing slash) — a bare `"/api"` prefix would also swallow SPA routes like `/api-keys` and `/api-keys/create`, forwarding them to the backend as 404s on hard refresh. Frontend validation: `npm run build` (runs `tsc --noEmit` first) and `npm test` (`node --test`, stdlib only). Testable logic lives in a plain `.ts` module with no runtime imports — `node --test` cannot load `.tsx` or resolve the `@/` alias; share types with `import type`, which type stripping erases. CI runs both (`web-build`, `web-test` jobs) on Node 24. No web lint script.
