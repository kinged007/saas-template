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
| `require_2fa` | off | Session requests on a workspace-scoped route are refused with 403 `2fa_required_for_workspace` when the session never cleared 2FA |
| `onboarding_enabled` | on | Dashboard hides the “Get set up” card when false |

Add a row here (and a code reference below) when a new flag lands.

Most flags are default-on and only ever disable something. `require_2fa` is
opt-in instead: enforcement is the exception, so a workspace that never set it
is unaffected, and turning it off removes the key rather than storing `false`.

## Where flags are enforced

- `WorkspaceService.create_invitation` refuses when `invites_enabled` is
  false (`apps/api/src/services/workspaces.py`).
- `enforce_workspace_security` refuses when `require_2fa` is set
  (`apps/api/src/api/deps.py`). Called from `require_permission` and
  `require_key_permission`.

## Writing a `require_2fa` flag

Unlike `invites_enabled`, the value is `true` only when enforcement is wanted,
so it is read with `.get(REQUIRE_2FA_FLAG) is True` (see
`apps/api/src/services/flags.py`) rather than the `is False` form the other
flags use.

Enforcement records the 2FA verdict on the session row
(`refresh_tokens.two_factor_verified_at`), not in the token: the access token
carries no 2FA claim, and the login challenge store is process-local and
single-use, so it cannot answer "did this session prove 2FA" on a later
request. The verdict is set at `POST /auth/2fa/login` and at
`POST /auth/2fa/enable` (enrolling mid-session proves possession just as well),
and `rotate_refresh` copies it onto the new session.

Exemptions are deliberate:

- **API keys.** A key is a server-side credential with its own permission list
  and no authenticator app. Enforcing 2FA would lock out every key already
  issued the moment the requirement is turned on.
- **The settings route itself** (`PATCH /workspaces/{id}/security`). An admin
  with no 2FA who turns the requirement on is otherwise locked out with no way
  to turn it off again. It declares `skip_workspace_security`.
- **Leaving a workspace** (`DELETE /workspaces/{id}/membership`). A member this
  setting refuses must still be able to walk away from it.
- **The WebSocket** at `ws://…/ws` is user-scoped, not workspace-scoped, so it
  stays outside the gate: a member this setting refuses still receives live
  notifications.

Every other route whose path carries a workspace id is gated, including
`POST /workspaces/{id}/transfer`, which calls `enforce_workspace_security`
directly because its authority is the owner role rather than a permission.

`onboarding_enabled` is the one flag also writable by non-superusers, through
`PATCH /workspaces/{id}` (`workspace:update`, i.e. owners and admins) rather
than the superuser-only flags endpoint. Enabling it does not clear anyone's
per-user dismissal, which is a localStorage choice each member makes for
themselves.
