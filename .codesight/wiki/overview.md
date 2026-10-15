# 211 — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**211** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

111 API routes · 23 database models · 67 UI components · 119 library files · 8 middleware layers · 45 environment variables

## Subsystems

- **[Auth](./auth.md)** — 22 routes — touches: auth, email, db, cache
- **[Admin](./admin.md)** — 6 routes — touches: db
- **[Api_keys](./api_keys.md)** — 5 routes — touches: db
- **[Conversations](./conversations.md)** — 9 routes
- **[Invitations](./invitations.md)** — 5 routes — touches: db, auth, email
- **[Jobs](./jobs.md)** — 11 routes — touches: auth
- **[Members](./members.md)** — 4 routes — touches: db
- **[Notifications](./notifications.md)** — 6 routes — touches: auth, db
- **[Oauth](./oauth.md)** — 2 routes — touches: auth, cache
- **[Profiles](./profiles.md)** — 15 routes — touches: db, auth
- **[Roles](./roles.md)** — 3 routes
- **[Webhooks](./webhooks.md)** — 11 routes — touches: webhook, db
- **[Workspaces](./workspaces.md)** — 8 routes — touches: db
- **[Infra](./infra.md)** — 4 routes

**Database:** sqlalchemy, 23 models — see [database.md](./database.md)

**UI:** 67 components (react) — see [ui.md](./ui.md)

**Libraries:** 119 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **66** files
- `apps/api/src/models/workspace.py` — imported by **47** files
- `apps/api/src/settings.py` — imported by **42** files
- `apps/api/tests/conftest.py` — imported by **38** files
- `apps/web/src/types.ts` — imported by **37** files
- `apps/api/src/core/dates.py` — imported by **35** files

## Required Environment Variables

- `CI` — `apps/web/playwright.config.ts`
- `DATABASE_URL` — `apps/api/tests/conftest.py`
- `EMAIL_FROM` — `apps/api/.env.example`
- `EMBEDDED_DB_DIR` — `apps/api/src/db/embedded.py`
- `FERNET_KEYS` — `infra/docker/.env.example`
- `NODE_ENV` — `apps/web/src/utils/storage.ts`
- `PATH` — `apps/api/tests/test_node_floor.py`
- `POSTGRES_PASSWORD` — `infra/docker/.env.example`
- `SECRET_KEY` — `infra/docker/.env.example`
- `SMTP_PASSWORD` — `apps/api/.env.example`
- `SMTP_USERNAME` — `apps/api/.env.example`
- `SUPERADMIN_EMAIL` — `apps/api/.env.example`
- _...1 more_

---
_Back to [index.md](./index.md) · Generated 2026-10-15_