# Feature Specification: Web extension seams

**Issue**: #1795 **Status**: Clarified **Areas**: none (no area labels on the issue; area context missing — see Assumptions)

## User Scenarios and Testing

### User Story 1 - Adopter adds a frontend page without editing template files (Priority: P1)

A team working in a project derived from the template adds a new frontend page — visible in navigation, reachable by URL, gated by permissions — by creating code only inside the project-owned extension area, without editing any template-owned file.

**Independent test**: Starting from the merged change, add a second page using only the project-owned extension area and confirm it renders, navigates, and respects permissions while the version-control diff shows zero template-owned files touched.

**Acceptance scenarios**:
1. Given the one-time integrations are in place, When an adopter adds a page solely in the project-owned area, Then the page renders at its own URL, appears as a sidebar menu item, and is gated by its declared permission exactly like a built-in page.

### User Story 2 - Template update does not conflict with adopter pages (Priority: P1)

An adopter taking a new template release wants their added pages to survive the merge without re-applying edits.

**Independent test**: Confirm via version control that everything an adopter added for a page lives under project-owned paths, so a template-side change to the integration points cannot textually conflict with it.

**Acceptance scenarios**:
1. Given adopter pages live only in the project-owned area, When a template update modifies the template-owned integration points, Then the adopter's pages need no re-application and merge without conflicts attributable to page additions.

### User Story 3 - Shipped demo proves every seam works (Priority: P2)

A template reviewer or new adopter opens the shipped demo page and sees all five contribution kinds (resource entry, route, menu item, permission-map entry, entity type) working together as the canonical example.

**Independent test**: With the demo present and unmodified, run the frontend build and unit-test suites, navigate to the demo URL as users with and without the required permission, and observe render, menu presence, and gating.

**Acceptance scenarios**:
1. Given the demo is present, When a user holding the demo's required permission navigates, Then the demo page renders and its sidebar entry is visible.
2. Given the demo is present, When a user lacking the demo's required permission navigates, Then the page is denied or hidden consistent with how built-in permission-gated pages behave.

## Requirements

- **FR-001**: The system MUST let project-owned code contribute resource-catalogue entries without per-page edits to template-owned code.
- **FR-002**: The system MUST let project-owned code contribute routes to the application route tree without per-page edits to template-owned code.
- **FR-003**: The system MUST let project-owned code contribute sidebar menu items to the navigation shell without per-page edits to template-owned code.
- **FR-004**: The system MUST let project-owned code contribute permission-map entries so project pages are gated exactly like built-in pages.
- **FR-005**: Project entity types MUST live in the project-owned area, separate from the template-owned shared types, which project code MUST NOT need to edit.
- **FR-006**: Each template-owned integration point (resource catalogue, navigation shell, permission map) MUST require at most a one-time change to consume project contributions; adding further pages MUST NOT touch template-owned files.
- **FR-007**: The change MUST ship a demo page exercising all five contribution kinds (resource, route, menu item, permission-map entry, entity type).
- **FR-008**: The frontend build (typecheck plus bundle) and the frontend unit-test suite MUST pass with the demo present and without special-casing it.
- **FR-009**: The change MUST carry a single adopter-facing release-note line stating what was added and what adopters must do.

## Acceptance Criteria

- **AC-1**: A demo page added only in the project-owned area renders at its own URL, appears as a sidebar menu item, and respects its declared permission for roles with and without it (covers FR-001, FR-002, FR-003, FR-004, FR-007).
- **AC-2**: After the change, adding a further page requires edits only under project-owned code; each of the three template-owned integration points changed at most once for the whole feature, verifiable via the version-control diff (covers FR-006).
- **AC-3**: The frontend build and unit-test suites pass unmodified with the demo present (covers FR-008).
- **AC-4**: No project entity type is declared in the template-owned shared types; every demo entity type resolves from the project-owned area (covers FR-005).
- **AC-5**: The change's PR description carries exactly one release-note line for this change (covers FR-009).

## Edge Cases

- Freshly seeded project with zero project contributions: the application renders exactly as before — no empty menu groups, no route errors, no permission-map regressions.
- A project resource with no permission-map entry follows the same default rule as an unmapped built-in resource; the demo MUST declare its entry so gating is actually proven, not defaulted.
- The demo MUST gate on a permission string that already exists in the product, so the change stays frontend-only with no backend or migration impact (one-area-per-change rule).
- A project route MUST NOT silently override a built-in route; both remain reachable after the change.
- Whether the demo is kept as the canonical example or removed before merge is the reviewer's call, not a merge blocker either way.

## Out of Scope

- Backend extension seams (routers, models, settings, jobs, workflow registration, migration branches) — separate phases of the parent update-path epic.
- The manual update procedure documentation, ownership manifest, path-check script and CI job, changelog entries, and release tagging — other phases of the parent epic.
- A general plugin, registry, or override framework beyond the five named contribution kinds (resource, route, menu item, permission-map entry, entity type).
- Visual or UX redesign of existing pages; the navigation shell's look and grouping behavior are unchanged.

## Clarifications

- Q: Does the current-phase freeze on new capabilities block this change? -> A: No — this change delivers the updatability guarantee as the web-seams phase of the parent update-path epic, which is explicitly in-phase work (chosen by agent from the parent issue and the product direction documents).
- Q: Does a project-owned extension area with one-time integration points violate the no-hook-layer rules? -> A: No — it keeps edit points few, small, and stable with adopters editing their own source, matching the documented exception for indirections that remove edit points (chosen by agent from the architecture decision records and admission gates).
- Q: Is the demo kept or removed at merge? -> A: Reviewer decides during build review, as the issue text already delegates (chosen by agent from the issue text).
