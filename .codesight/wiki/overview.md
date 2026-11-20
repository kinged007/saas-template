# 267 — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**267** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

124 API routes · 23 database models · 64 UI components · 106 library files · 4 middleware layers · 39 environment variables

## Subsystems

- **[Auth](./auth.md)** — 21 routes — touches: auth, email, db, cache
- **[Admin](./admin.md)** — 6 routes — touches: db
- **[Api_keys](./api_keys.md)** — 5 routes — touches: db
- **[Conversations](./conversations.md)** — 9 routes
- **[Invitations](./invitations.md)** — 5 routes — touches: db, auth, email
- **[Jobs](./jobs.md)** — 11 routes — touches: auth
- **[Members](./members.md)** — 4 routes — touches: db
- **[Notifications](./notifications.md)** — 6 routes — touches: auth, db
- **[Oauth](./oauth.md)** — 2 routes — touches: auth, cache
- **[Profiles](./profiles.md)** — 8 routes — touches: db, auth
- **[Roles](./roles.md)** — 3 routes
- **[Webhooks](./webhooks.md)** — 10 routes — touches: webhook, db
- **[Workspaces](./workspaces.md)** — 8 routes — touches: db
- **[Infra](./infra.md)** — 4 routes

**Database:** sqlalchemy, 23 models — see [database.md](./database.md)

**UI:** 64 components (react) — see [ui.md](./ui.md)

**Libraries:** 106 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **53** files
- `apps/api/src/settings.py` — imported by **38** files
- `apps/api/src/models/workspace.py` — imported by **36** files
- `apps/web/src/types.ts` — imported by **31** files
- `apps/api/tests/conftest.py` — imported by **30** files
- `apps/api/src/core/dates.py` — imported by **26** files

## Required Environment Variables

- `CI` — `apps/web/playwright.config.ts`
- `DATABASE_URL` — `apps/api/tests/conftest.py`
- `EMAIL_FROM` — `apps/api/.env.example`
- `EMBEDDED_DB_DIR` — `apps/api/src/db/embedded.py`
- `SMTP_PASSWORD` — `apps/api/.env.example`
- `SMTP_USERNAME` — `apps/api/.env.example`
- `SUPERADMIN_EMAIL` — `apps/api/.env.example`
- `WEB_PORT` — `apps/web/vite.config.ts`

---
_Back to [index.md](./index.md) · Generated 2026-09-30_