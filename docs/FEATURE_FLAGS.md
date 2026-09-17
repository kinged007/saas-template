# Feature flags

Workspace-level feature toggles live in `workspaces.flags`, a JSON object
`{key: bool}`. There is no separate model or table — a column keeps flags
co-located with the workspace they gate, with no extra join.

## Convention

- Key: `snake_case` capability name, e.g. `invites_enabled`.
- Value: boolean. **An absent key means default-on** — new flags must not
  change behavior for existing workspaces until explicitly set.
- Read: `(workspace.flags or {}).get("<key>") is False` means disabled.
- Enforcement lives in the service layer (`WorkspaceService`), so API keys,
  session users, and future callers all share the gate.

## Registry

| Flag | Default | Gates |
| ---- | ------- | ----- |
| `invites_enabled` | on | `WorkspaceService.create_invitation` refuses with 403 when `False` |

## Adding a flag

1. Add a row to the registry above.
2. Gate in the service method (`... is False` check raising `WorkspaceForbidden`).
3. Map `WorkspaceForbidden` to 403 in the route (invitations already does).
4. Add a test in `tests/test_admin.py`.

<!-- ponytail: single-column JSON; move to a dedicated table past ~5 flags. -->
