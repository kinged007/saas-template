# Feature Flags

Workspace-level feature toggles stored on `workspaces.flags` (JSON object,
`{key: bool}`). A missing key means **default-on** — flags only ever disable
something, so new workspaces need no backfill.

## Convention

- Key: `snake_case` capability name, e.g. `invites_enabled`.
- Value: boolean. Non-boolean values are ignored (treated as default-on).
- Merge-patch update via `PATCH /admin/workspaces/{id}/flags`
  (`{"flags": {"key": false}}`); keys not mentioned keep their values.
- Reads use `(workspace.flags or {}).get(key) is False` to decide "disabled".

## Registry

| Flag | Default | Gates |
|------|---------|-------|
| `invites_enabled` | on | `POST /invitations` refuses with 409 when false |

Add a row here (and a code reference below) when a new flag lands.

## Where flags are enforced

- `WorkspaceService.create_invitation` refuses when `invites_enabled` is
  false (`apps/api/src/services/workspaces.py`).
