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

---

## Agent Instructions

This project uses codesight for structured AI context. Follow these steps before implementing:
1. Read `.codesight/wiki/index.md` for project orientation (~200 tokens)
2. Read `.codesight/wiki/overview.md` for architecture overview (~500 tokens)
3. Read the relevant domain article, then open the source files listed in it
4. Read `.codesight/CODESIGHT.md` for the full context map

**Do not explore the file tree blindly.** The codesight context map already contains:
routes, schema, components, libraries, config, middleware, and dependency graph.

**Before modifying any file:** check `.codesight/graph.md` for blast radius.
Files with high import counts affect many downstream modules — change carefully.

Routes marked `[inferred]` were detected via regex and may have lower precision.
If any source file shows ⚠ in a wiki article, re-run `npx codesight --wiki` before proceeding.

---

## Frontend

**Skill:** `refine-dev` (itechmeat-llm-code-refine-dev) is installed for opencode (`~/.agents/skills/itechmeat-llm-code-refine-dev/SKILL.md`) and Claude Code (`.claude/skills/itechmeat-llm-code-refine-dev/SKILL.md`). Load it for Refine.dev API details, but the canonical rules below and existing repo patterns take precedence over the skill's generic guidance (e.g. it assumes Mantine; this repo uses shadcn/ui).

**Stack (apps/web):** Refine **v5** (`@refinedev/core`, `@refinedev/react-router`) + custom `dataProvider` (wraps `@refinedev/simple-rest`) + `accessControlProvider` + sonner `notificationProvider`. shadcn/ui components in `src/components/ui/`; refine primitives (views, buttons, layout) in `src/components/refine-ui/`. Forms use `@refinedev/react-hook-form` + `react-hook-form` + `zod` + `@hookform/resolvers`.

**Refine-canonical rules (apply to all new pages; migrate old ones):**
- Register `create` on every resource in `src/App.tsx` (`{ name: "x", list: "/x", create: "/x/create" }`). **Create must be a page, never a dialog** on the list page.
- List pages use `ListView` + `ListViewHeader`. The `canCreate` slot renders the built-in `CreateButton`, which **links** to the create route (it cannot open dialogs) and is ACL-aware via `useCreateButton` (default `hideIfUnauthorized: false` → shows disabled). Do not hand-roll `PageHeader` + dialog; do not modify shared refine-ui components to special-case one page.
- Create pages use `CreateView` + `CreateViewHeader` (both in `src/components/refine-ui/views/create-view.tsx`) with `useForm` from `@refinedev/react-hook-form` (`refineCoreProps: { resource, action: "create" }`), `zodResolver`, and shadcn `Form` components (`FormField`/`FormItem`/`FormLabel`/`FormControl`/`FormMessage`). `onFinish` returns the created record and invalidates the list cache automatically.
- Navigation: `useNavigation().list("resource")` / `useGo` — not raw react-router `navigate`.
- Data fetching: `useList` / `useCustom` / `useCustomMutation`; custom URLs are relative to `/api/v1` (the dataProvider resolves them). Mutations use `useCreate`/`useUpdate`/`useDelete` on resources, not `useCustomMutation`, where possible.
- Access control: `accessControlProvider` maps (resource, action) → backend permission string (see `PERMISSION_MAP`). Gate UI with `useCan` / `CreateButton` / `<CanAccess>`; the backend is always the final authority.
- Notifications: set `successNotification` in `refineCoreProps`. Suppress refine's generic error toast (`errorNotification: false`) when showing the server `detail` yourself — the dataProvider already surfaces FastAPI `detail` as `error.message`.
- Keep API/entity types in `src/types.ts` (high-impact file — change carefully).

**Not yet canonical (migrate to the patterns above when touched):** RolesPage, MembersPage, WorkspaceCreatePage, ReceivedInvitationsPage (use `PageHeader`/`useCreate`/dialogs instead of views + `useForm`).

**Dev notes:** Vite's proxy rule is `"/api/"` (trailing slash) — a bare `"/api"` prefix would also swallow SPA routes like `/api-keys` and `/api-keys/create`, forwarding them to the backend as 404s on hard refresh. Frontend validation: `npm run build` (runs `tsc --noEmit` first). No web lint script.

## Quick start (development — all terminal, no docker)

The dev stack is self-contained: the API embeds PostgreSQL (via `pgserver`,
real Postgres 16 binaries, data in `~/.local/share/saas-template/pgdata`) and
consumes events asynchronously in-process. Switching to NATS JetStream is a
single env var swap (`EVENT_BUS_DRIVER=nats`).

```bash
make setup  # one-time: installs uv + Node.js if missing (tries fnm, then apt, then nvm)
make dev    # install deps, migrate, seed, then run api (:8000) + web (:5173)
```

For more commands, read README.md