# saas-template — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**saas-template** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

26 API routes · 10 database models · 28 UI components · 45 library files · 2 middleware layers · 18 environment variables

## Subsystems

- **[Auth](./auth.md)** — 5 routes — touches: auth
- **[Api_keys](./api_keys.md)** — 4 routes — touches: db
- **[Invitations](./invitations.md)** — 4 routes — touches: db, auth
- **[Members](./members.md)** — 2 routes — touches: db
- **[Notifications](./notifications.md)** — 3 routes — touches: db
- **[Roles](./roles.md)** — 2 routes
- **[Workspaces](./workspaces.md)** — 3 routes — touches: db
- **[Infra](./infra.md)** — 3 routes

**Database:** sqlalchemy, 10 models — see [database.md](./database.md)

**UI:** 28 components (react) — see [ui.md](./ui.md)

**Libraries:** 45 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **21** files
- `apps/api/src/models/workspace.py` — imported by **14** files
- `apps/web/src/types.ts` — imported by **13** files
- `apps/api/src/events/bus.py` — imported by **12** files
- `apps/api/src/settings.py` — imported by **11** files
- `apps/api/src/services/workspaces.py` — imported by **10** files

## Required Environment Variables

- `DATABASE_URL` — `apps/api/tests/conftest.py`

---
_Back to [index.md](./index.md) · Generated 2026-08-20_