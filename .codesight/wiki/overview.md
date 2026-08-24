# saas-template — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**saas-template** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

37 API routes · 13 database models · 31 UI components · 53 library files · 2 middleware layers · 22 environment variables

## Subsystems

- **[Auth](./auth.md)** — 5 routes — touches: auth
- **[Api_keys](./api_keys.md)** — 4 routes — touches: db
- **[Invitations](./invitations.md)** — 4 routes — touches: db, auth
- **[Jobs](./jobs.md)** — 11 routes — touches: auth
- **[Members](./members.md)** — 2 routes — touches: db
- **[Notifications](./notifications.md)** — 3 routes — touches: db
- **[Roles](./roles.md)** — 2 routes
- **[Workspaces](./workspaces.md)** — 3 routes — touches: db
- **[Infra](./infra.md)** — 3 routes

**Database:** sqlalchemy, 13 models — see [database.md](./database.md)

**UI:** 31 components (react) — see [ui.md](./ui.md)

**Libraries:** 53 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **28** files
- `apps/web/src/types.ts` — imported by **16** files
- `apps/api/src/models/workspace.py` — imported by **15** files
- `apps/api/src/settings.py` — imported by **14** files
- `apps/api/src/events/bus.py` — imported by **13** files
- `apps/api/src/services/workspaces.py` — imported by **11** files

## Required Environment Variables

- `DATABASE_URL` — `apps/api/tests/conftest.py`
- `SUPERADMIN_EMAIL` — `apps/api/.env.example`

---
_Back to [index.md](./index.md) · Generated 2026-08-24_