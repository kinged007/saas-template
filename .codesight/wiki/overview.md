# saas-template — Overview

> **Navigation aid.** This article shows WHERE things live (routes, models, files). Read actual source files before implementing new features or making changes.

**saas-template** is a typescript project built with fastapi, using sqlalchemy for data persistence, organized as a monorepo.

**Workspaces:** `api` (`apps/api`), `saas-template-web` (`apps/web`)

## Scale

62 API routes · 19 database models · 68 UI components · 122 library files · 5 middleware layers · 33 environment variables

## Subsystems

- **[Auth](./auth.md)** — 5 routes — touches: auth
- **[Agents](./agents.md)** — 8 routes — touches: db
- **[Api_keys](./api_keys.md)** — 2 routes — touches: db
- **[Conversations](./conversations.md)** — 9 routes — touches: auth, db
- **[Invitations](./invitations.md)** — 4 routes — touches: db, auth
- **[Jobs](./jobs.md)** — 11 routes — touches: auth
- **[Members](./members.md)** — 2 routes — touches: db
- **[Notifications](./notifications.md)** — 2 routes — touches: db
- **[Profiles](./profiles.md)** — 8 routes — touches: db
- **[Roles](./roles.md)** — 2 routes
- **[Workspace_settings](./workspace_settings.md)** — 3 routes — touches: db
- **[Workspaces](./workspaces.md)** — 3 routes — touches: db
- **[Infra](./infra.md)** — 3 routes

**Database:** sqlalchemy, 19 models — see [database.md](./database.md)

**UI:** 68 components (react) — see [ui.md](./ui.md)

**Libraries:** 122 files — see [libraries.md](./libraries.md)

## High-Impact Files

Changes to these files have the widest blast radius across the codebase:

- `apps/api/src/db/session.py` — imported by **37** files
- `apps/web/src/types.ts` — imported by **23** files
- `apps/api/src/models/workspace.py` — imported by **22** files
- `apps/api/src/settings.py` — imported by **20** files
- `apps/api/src/events/bus.py` — imported by **18** files
- `apps/api/src/events/subjects.py` — imported by **15** files

## Required Environment Variables

- `ATLASSIAN_API_TOKEN` — `agent/skills/atlassian-rest/scripts/confluence.mjs`
- `ATLASSIAN_DOMAIN` — `agent/skills/atlassian-rest/scripts/confluence.mjs`
- `ATLASSIAN_EMAIL` — `agent/skills/atlassian-rest/scripts/confluence.mjs`
- `DATABASE_URL` — `apps/api/tests/conftest.py`
- `DEV` — `agent/skills/slide-maker/deck-template/src/App.jsx`
- `EMBEDDED_DB_DIR` — `apps/api/src/db/embedded.py`
- `GEMINI_IMAGE_GEN_MODEL` — `agent/skills/ai-multimodal/scripts/gemini_batch_process.py`
- `GEMINI_MODEL` — `agent/skills/ai-multimodal/scripts/gemini_batch_process.py`
- `IMAGE_GEN_MODEL` — `agent/skills/ai-multimodal/scripts/gemini_batch_process.py`
- `MULTIMODAL_MODEL` — `agent/skills/ai-multimodal/scripts/gemini_batch_process.py`
- `VIDEO_GEN_MODEL` — `agent/skills/ai-multimodal/scripts/gemini_batch_process.py`
- `VITE_EDIT` — `agent/skills/slide-maker/deck-template/src/App.jsx`

---
_Back to [index.md](./index.md) · Generated 2026-08-30_