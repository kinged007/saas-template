# web-app

Paths: `apps/web/src/**` (`App.tsx`, `main.tsx`, `types.ts`, `pages/`, `components/`, `providers/`, `hooks/`, `contexts/`, `lib/`, `utils/`), `apps/web/package.json`, `package-lock.json`, `vite.config.ts`, `tsconfig.json`, `tailwind.config.js`, `components.json`, `index.html`, `.env.example`.

Purpose: Refine v5 single-page app with shadcn/ui components, talking to the API under `/api/v1`.

Entry points:
- `src/main.tsx`, `src/App.tsx`: resources and `<Routes>`.
- `src/providers/`: `dataProvider.ts`, `authProvider.ts`, `accessControlProvider.ts` (`PERMISSION_MAP`), `liveProvider.ts`.
- `src/types.ts`: API and entity types (imported by 12 files).
- `src/pages/settings/{user,workspace,profile}/registry.ts`, `src/pages/admin/registry.ts`: settings and admin sections.

Conventions (from `AGENTS.md`):
- Register `create` on every resource in `App.tsx`; create is a page, not a dialog.
- List pages use `ListView`, create pages use `CreateView` with refine `useForm`, zod and shadcn `Form`.
- Use `useNavigation`, `useList`, `useCustom`, `useCan` / `<CanAccess>`; custom URLs are relative to `/api/v1`.
- Testable logic goes in plain `.ts` modules with no runtime imports and no `@/` alias; `node --test` cannot load `.tsx`.
- `RolesPage`, `MembersPage`, `WorkspaceCreatePage`, `ReceivedInvitationsPage` are not yet canonical.

Pitfalls:
- The Vite proxy rule is `"/api/"` with a trailing slash so routes like `/api-keys` are not proxied.
- No lint script exists.

Checks (CI jobs `web-build`, `web-test`, Node 24):
- `cd apps/web && npm run build`
- `cd apps/web && npm test`
