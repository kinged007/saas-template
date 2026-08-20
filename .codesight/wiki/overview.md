# saas-template — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**saas-template** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

26 API routes · 10 database models · 26 UI components · 43 library files · 2 middleware layers · 17 environment variables

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

**UI:** 26 components (react) — see [ui.md](./ui.md)

**Libraries:** 43 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **16** files
- `apps/api/src/models/workspace.py` — imported by **12** files
- `apps/web/src/types.ts` — imported by **12** files
- `apps/api/src/settings.py` — imported by **9** files
- `apps/api/src/services/workspaces.py` — imported by **9** files
- `apps/api/src/api/deps.py` — imported by **9** files

## Required Environment Variables

- `DATABASE_URL` — `apps/api/tests/conftest.py`

---
_Back to [index.md](./index.md) · Generated 2026-08-20_