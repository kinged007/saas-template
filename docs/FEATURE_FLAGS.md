# Feature Flags

Workspace-level feature toggles stored on `workspaces.flags` (JSON object,
`{key: bool}`). A missing key means **default-on** — flags only ever disable
something, so new workspaces need no backfill.

## Convention

- Key: `snake_case` capability name, e.g. `invites_enabled`.
- Value: boolean. The write path rejects non-booleans with 422; a non-bool that somehow reaches the DB is ignored on read (treated as default-on).
- Merge-patch update via `PATCH /admin/workspaces/{id}/flags`
  (`{"flags": {"key": false}}`); keys not mentioned keep their values.
- Reads use `(workspace.flags or {}).get(key) is False` to decide "disabled".

## Registry

| Flag | Default | Gates |
|------|---------|-------|
| `invites_enabled` | on | `POST /invitations` refuses with 409 when false |
| `onboarding_enabled` | on | Dashboard hides the “Get set up” card when false |

Add a row here (and a code reference below) when a new flag lands.

## Where flags are enforced

- `WorkspaceService.create_invitation` refuses when `invites_enabled` is
  false (`apps/api/src/services/workspaces.py`).
- The dashboard “Get set up” card is hidden when `onboarding_enabled` is
  false (`apps/web/src/pages/DashboardPage.tsx`).

`onboarding_enabled` is the one flag also writable by non-superusers, through
`PATCH /workspaces/{id}` (`workspace:update`, i.e. owners and admins) rather
than the superuser-only flags endpoint. Enabling it does not clear anyone's
per-user dismissal, which is a localStorage choice each member makes for
themselves.
