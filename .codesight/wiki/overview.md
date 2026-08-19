# saas-template — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**saas-template** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

24 API routes · 9 database models · 23 UI components · 40 library files · 2 middleware layers · 17 environment variables

## Subsystems

- **[Auth](./auth.md)** — 5 routes — touches: auth
- **[Invitations](./invitations.md)** — 6 routes — touches: db, auth
- **[Members](./members.md)** — 2 routes — touches: db
- **[Notifications](./notifications.md)** — 3 routes — touches: db
- **[Roles](./roles.md)** — 2 routes
- **[Workspaces](./workspaces.md)** — 3 routes — touches: db
- **[Infra](./infra.md)** — 3 routes

**Database:** sqlalchemy, 9 models — see [database.md](./database.md)

**UI:** 23 components (react) — see [ui.md](./ui.md)

**Libraries:** 40 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **14** files
- `apps/api/src/models/workspace.py` — imported by **10** files
- `apps/web/src/types.ts` — imported by **10** files
- `apps/api/src/settings.py` — imported by **9** files
- `apps/api/src/api/deps.py` — imported by **8** files
- `apps/api/src/models/core.py` — imported by **8** files

## Required Environment Variables

- `DATABASE_URL` — `apps/api/tests/conftest.py`

---
_Back to [index.md](./index.md) · Generated 2026-08-19_