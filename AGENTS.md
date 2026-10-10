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
After changing any model: `make db-new m="..."`, review the diff (watch for
accidental drops, wrong nullability, missing server_default), commit the file.
`make db-check` (also in CI) fails on multiple heads or models≠migrations.
Full workflow: `docs/MIGRATIONS.md`.

## Cookie `Secure` precedence

`cookie_secure_for()` (`apps/api/src/core/security/cookies.py`) decides the
refresh-cookie `Secure` flag. When it or `REFRESH_COOKIE_SECURE` changes,
restate the precedence identically in all three places, override first:
`apps/api/.env.example` (`REFRESH_COOKIE_SECURE` comment), `docs/ARCHITECTURE.md`
§5 auth flows table, and `docs/ARCHITECTURE.md` §9 security list. Behavior is
covered by `apps/api/tests/test_auth_cookie.py`; no doc-lint exists yet — add
one only if the wording drifts again.

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

**Dev notes:** Vite's proxy rule is `"/api/"` (trailing slash) — a bare `"/api"` prefix would also swallow SPA routes like `/api-keys` and `/api-keys/create`, forwarding them to the backend as 404s on hard refresh. Frontend validation: `npm run build` (runs `tsc --noEmit` first) and `npm test` (`node --test`, stdlib only). Testable logic lives in a plain `.ts` module with no runtime imports — `node --test` cannot load `.tsx` or resolve the `@/` alias; share types with `import type`, which type stripping erases. CI runs both (`web-build`, `web-test` jobs) on Node 24. No web lint script.