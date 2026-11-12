# Plan — #1072 a11y: document the heading convention and apply it to the refine-ui page shells

**Source of requirements:** no `spec.md` exists for this item. The requirements come from the issue description and the owner's routing comment (2026-10-11): one component (the refine-ui page shells and their consumers), docs and application in one PR, no new public interface, no dependency; the plan names the convention (one level-1 heading per page, owned by the shell, asserted by a landmark test), the files and the order. The routing comment groups #1616 with this item and says the PM closes #1616 when this PR merges, so the #1616 fix is in scope (AC-5).

## Acceptance criteria (derived)

- **AC-1** The heading convention is written in the root `AGENTS.md`, Frontend section: the page title is the single `h1` of the page and the page shell renders it; card and section titles directly under it are `h2` (sub-sections `h3`, no skipped level); landmark and overlay titles (sidebar nav group headings, dialog/sheet titles) stay `h2`.
- **AC-2** The page shells render the page title as `h1`: `ListViewHeader` (`components/refine-ui/views/list-view.tsx`), `CreateViewHeader` (`components/refine-ui/views/create-view.tsx`), `PageHeader` (`components/refine-ui/layout/page-header.tsx`), `TabbedPageHeader` (`components/refine-ui/layout/tabbed-page-header.tsx`) and `PageHeader` in `components/ui.tsx`. Class names stay the same, so the visual output does not change.
- **AC-3** Section headings that consumers place directly under a shell title move from `h3` to `h2`, so no page outline skips a level: `pages/JobsPage.tsx:166` ("Global jobs"), `pages/MembersPage.tsx:353` ("Invited members"), `pages/InboxPage.tsx:872` (conversation title), `pages/InboxPage.tsx:1231` (notification title).
- **AC-4** A Playwright landmark test asserts that each shell route has exactly one `h1` inside the page `<main>`, with the expected name, and that the outline inside `<main>` starts at `H1` and never skips a level.
- **AC-5** (#1616) `WorkspaceSettingsLayout` and `AdminLayout` each hold their title in one `const title` used for both the `h1` and the `SettingsNav` `label`.

## Approach

The shells already own the title text, so the fix is to change the tag in each shell from `h2` to `h1`. Each consuming page gets the correct `h1` without edits. Pages render a single shell, so each page then has one `h1`. Four consumer section headings sit at `h3` under the former `h2` title; they move to `h2` so the outline has no gap.

The convention goes into the root `AGENTS.md` Frontend section, next to the other refine-canonical rules that agents and contributors read before UI work. `docs/ARCHITECTURE.md` covers backend and API contract topics, so it is not the place for this rule.

The guard is a Playwright spec (`apps/web/e2e/page-headings.spec.ts`), the same kind as `e2e/dashboard-a11y.spec.ts` and `e2e/sidebar-landmark.spec.ts`: it reads the rendered DOM, so it checks what assistive technology reads. It reuses the `pageBody` (`page.locator("main").last()`) and `outline` helpers pattern from `dashboard-a11y.spec.ts` (copied locally; no shared helper module is introduced for two callers).

`apps/web/src/components/ui/card-title-classes.test.ts` is **not** widened. The issue says to widen it only if the rule holds app-wide; `pages/JobRunPage.tsx:88` and `pages/JobDetailPage.tsx:351` still render their page titles as hand-written `h2` without a shell, so the rule does not hold app-wide after this change. Those two pages are outside the scope ceiling (they are not refine-ui shell consumers) and are listed as a follow-up in the PR body.

Order: docs (AC-1) → failing e2e spec (AC-4) → shells (AC-2) → consumer sections (AC-3) → #1616 hoist (AC-5) → quality gate.

## Files to change

| Path | Change |
| --- | --- |
| `AGENTS.md` | Add a "Headings" rule to the Frontend section (AC-1). |
| `apps/web/e2e/page-headings.spec.ts` | New. One test per shell route: `/members`, `/invitations`, `/api-keys`, `/api-keys/create`, `/webhooks`, `/webhooks/create`, `/workspaces/create`, `/inbox`; `/jobs` only if `e2e/mock-api.ts` serves its requests (no current spec visits `/jobs`; if it does not, `/jobs` is covered by the build and the AGENTS.md rule only, and the PR body says so). Each test asserts exactly one `h1` in `main` with the expected name and a level-gap-free outline (AC-4). |
| `apps/web/src/components/refine-ui/views/list-view.tsx` | `<h2 className="text-2xl font-bold">` → `<h1 …>` (AC-2). |
| `apps/web/src/components/refine-ui/views/create-view.tsx` | Same (AC-2). |
| `apps/web/src/components/refine-ui/layout/page-header.tsx` | Same (AC-2). |
| `apps/web/src/components/refine-ui/layout/tabbed-page-header.tsx` | Same, keeping `truncate` (AC-2). |
| `apps/web/src/components/ui.tsx` | `PageHeader` `h2` → `h1` (AC-2). This export has no importer today; it is changed, not deleted, to keep the diff inside the issue's scope. |
| `apps/web/src/pages/JobsPage.tsx` | Line 166 `h3` → `h2` (AC-3). |
| `apps/web/src/pages/MembersPage.tsx` | Line 353 `h3` → `h2` (AC-3). |
| `apps/web/src/pages/InboxPage.tsx` | Lines 872 and 1231 `h3` → `h2` (AC-3). |
| `apps/web/src/pages/settings/workspace/WorkspaceSettingsLayout.tsx` | Hoist `"Workspace Settings"` to `const title`, use it at the `h1` (line 86) and `SettingsNav label` (line 95) (AC-5). |
| `apps/web/src/pages/admin/sections/AdminLayout.tsx` | Hoist `"Administration"` to `const title`, use it at the `h1` (line 43) and `SettingsNav label` (line 55) (AC-5). |

Expected `h1` names per route are read from the resource `meta.label` / page `title` props in `apps/web/src/App.tsx` and each page during implementation, then pinned in the spec.

## Data and contract changes

None. No API, schema, persisted data, config or dependency change. Component props are unchanged; only the rendered heading level changes.

## Test plan

Tests first:

- **AC-4 / AC-2 / AC-3:** write `apps/web/e2e/page-headings.spec.ts` before the shell edits and run it; it must fail on every shell route (no `h1` today). After the shell and consumer edits it passes. Run `apps/web/e2e/dashboard-a11y.spec.ts`, `sidebar-landmark.spec.ts`, `member-settings.spec.ts`, `inbox-a11y.spec.ts` and `onboarding-*.spec.ts` as regression, since they query headings by level or name.
- For the Inbox route, the outline check runs with a selected conversation (as in `inbox-a11y.spec.ts:116`) so the conversation-title `h2` (AC-3) is in the DOM.
- **AC-5:** covered by the existing `e2e/sidebar-landmark.spec.ts` (workspace settings nav named after the `h1`); no new test, the change is a refactor of a string literal.
- **AC-1:** documentation; checked by review.

Smoke test: `cd apps/web && npm run build` (tsc + vite build of the shipped bundle), then the e2e suite above, which runs the built app against the mock API through Playwright (`apps/web/playwright.config.ts`).

Quality gate (from `.github/workflows` jobs `web-build`, `web-test`, `web-e2e` and the root `AGENTS.md` Frontend dev notes): `cd apps/web && npm run build`, `npm test`, `npm run test:e2e`. The repo has no web lint script.

## Risks

- **Existing e2e selectors by level.** Specs that query `getByRole("heading", { level: 2 })` for a shell title would break. The grep found none (`level: 2` is only used for "Get set up" on the dashboard), but the full e2e run confirms it.
- **Pages with a second `h1`.** If a consumer renders its own `h1` besides the shell, the page gets two. The grep found no `h1` in any shell consumer; the new spec asserts exactly one.
- **`/jobs` mock coverage.** `e2e/mock-api.ts` may not serve the jobs endpoints; handled as described in Files to change.
- **Browser default `h1` styles.** Tailwind preflight resets heading sizes, so `text-2xl font-bold` renders the same on `h1` as on `h2`.

## Rollback

Revert the single PR commit. No data or config is involved, so the revert has no side effects.
