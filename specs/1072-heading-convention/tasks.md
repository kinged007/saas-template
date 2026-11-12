# Tasks — #1072

## Phase 1: Setup and tests first

- [ ] T001 [AC-1] AGENTS.md — add the heading convention to the Frontend section: page title is the single `h1`, rendered by the page shell; card/section titles under it are `h2`, sub-sections `h3`, no skipped level; sidebar nav group headings and dialog/sheet titles stay `h2`
- [ ] T002 [AC-4] apps/web/e2e/page-headings.spec.ts — new spec: for `/members`, `/invitations`, `/api-keys`, `/api-keys/create`, `/webhooks`, `/webhooks/create`, `/workspaces/create`, `/inbox` (and `/jobs` if `e2e/mock-api.ts` serves it) assert exactly one `h1` in `page.locator("main").last()` with the expected name and an outline that starts at H1 with no skipped level
- [ ] T003 [AC-4] apps/web/e2e/page-headings.spec.ts — run `npm run test:e2e -- page-headings` from `apps/web` and confirm it fails on every route before the shell edits

## Phase 2: Implementation

- [ ] T004 [P] [AC-2] apps/web/src/components/refine-ui/views/list-view.tsx — title `h2` → `h1`, classes unchanged
- [ ] T005 [P] [AC-2] apps/web/src/components/refine-ui/views/create-view.tsx — title `h2` → `h1`, classes unchanged
- [ ] T006 [P] [AC-2] apps/web/src/components/refine-ui/layout/page-header.tsx — title `h2` → `h1`, classes unchanged
- [ ] T007 [P] [AC-2] apps/web/src/components/refine-ui/layout/tabbed-page-header.tsx — title `h2` → `h1`, classes unchanged
- [ ] T008 [P] [AC-2] apps/web/src/components/ui.tsx — `PageHeader` title `h2` → `h1`
- [ ] T009 [P] [AC-3] apps/web/src/pages/JobsPage.tsx — "Global jobs" `h3` → `h2`
- [ ] T010 [P] [AC-3] apps/web/src/pages/MembersPage.tsx — "Invited members" `h3` → `h2`
- [ ] T011 [P] [AC-3] apps/web/src/pages/InboxPage.tsx — conversation title and notification title `h3` → `h2`
- [ ] T012 [P] [AC-5] apps/web/src/pages/settings/workspace/WorkspaceSettingsLayout.tsx — hoist `"Workspace Settings"` to `const title`, use it for the `h1` and `SettingsNav label`
- [ ] T013 [P] [AC-5] apps/web/src/pages/admin/sections/AdminLayout.tsx — hoist `"Administration"` to `const title`, use it for the `h1` and `SettingsNav label`

## Phase 3: Polish

- [ ] T014 [AC-4] apps/web/e2e/page-headings.spec.ts — rerun; all routes pass
- [ ] T015 Quality gate — from `apps/web`: `npm run build`, `npm test`, `npm run test:e2e` (full suite, covers the heading-level regression specs and the smoke test)
- [ ] T016 PR body — note that `card-title-classes.test.ts` is not widened because `pages/JobRunPage.tsx` and `pages/JobDetailPage.tsx` still use hand-written `h2` page titles (follow-up), and that the PR resolves #1616 without a closing keyword for it
