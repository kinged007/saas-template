# saas-template — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**saas-template** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

94 API routes · 23 database models · 61 UI components · 99 library files · 3 middleware layers · 35 environment variables

## Subsystems

- **[Auth](./auth.md)** — 20 routes — touches: auth, email, db, cache
- **[Admin](./admin.md)** — 6 routes — touches: db
- **[Api_keys](./api_keys.md)** — 5 routes — touches: db
- **[Conversations](./conversations.md)** — 8 routes
- **[Invitations](./invitations.md)** — 4 routes — touches: db, auth
- **[Jobs](./jobs.md)** — 11 routes — touches: auth
- **[Members](./members.md)** — 2 routes — touches: db
- **[Notifications](./notifications.md)** — 6 routes — touches: auth, db
- **[Oauth](./oauth.md)** — 2 routes — touches: auth, cache
- **[Profiles](./profiles.md)** — 8 routes — touches: db
- **[Roles](./roles.md)** — 3 routes
- **[Webhooks](./webhooks.md)** — 10 routes — touches: webhook, db
- **[Workspaces](./workspaces.md)** — 5 routes — touches: db
- **[Infra](./infra.md)** — 4 routes

**Database:** sqlalchemy, 23 models — see [database.md](./database.md)

**UI:** 61 components (react) — see [ui.md](./ui.md)

**Libraries:** 99 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **44** files
- `apps/api/src/settings.py` — imported by **32** files
- `apps/api/src/models/workspace.py` — imported by **30** files
- `apps/web/src/types.ts` — imported by **27** files
- `apps/api/tests/conftest.py` — imported by **23** files
- `apps/api/src/models/core.py` — imported by **19** files

## Required Environment Variables

- `DATABASE_URL` — `apps/api/tests/conftest.py`
- `EMAIL_FROM` — `apps/api/.env.example`
- `EMBEDDED_DB_DIR` — `apps/api/src/db/embedded.py`
- `SMTP_PASSWORD` — `apps/api/.env.example`
- `SMTP_USERNAME` — `apps/api/.env.example`
- `SUPERADMIN_EMAIL` — `apps/api/.env.example`

---
_Back to [index.md](./index.md) · Generated 2026-09-23_