# PR #186 review follow-up

## Scope

- PR: https://github.com/kinged007/saas-template/pull/186
- Title: `feat(auth,profile): change-password with 2FA gate + my-workspaces tab`
- Base: `main`
- Head branch: `auto/174-173`
- Preserved baseline: `0858ca084531d0dc8fed28afa2c65ed3f02be7e9`
- This follow-up was prepared in `/home/coder/orca/workspaces/saas-template/auto-saas-template-pr-review-run-81-20260925T0000`.

The PR was already marked **MERGED** by an external process at `2026-09-25T12:05:48Z` with merge commit `b6f63990ece9440474fb8dac424b28ed62033c86` before this follow-up was pushed. This run did not merge, close, approve, reopen, or otherwise finalize the PR.

## Findings addressed

### Change-password authentication and rate limiting

- `apps/api/src/services/auth.py::AuthService.verify_password` now performs password validation without updating `last_login_at` or publishing a login audit event.
- `apps/api/src/services/auth.py::AuthService.login_password` retains its existing login side effects by calling the new verifier first.
- `apps/api/src/api/routes/auth.py::change_password` now:
  - keeps authenticated validation failures as HTTP 400;
  - counts a wrong current password, missing 2FA code, invalid 2FA code, and `TwoFactorError` as limiter failures;
  - resets the limiter only after the password change and session revocation complete.
- Regression coverage is in `apps/api/tests/test_auth_change_password.py`, including the no-login-side-effect and limiter cases.

### Workspace membership and leave behavior

- `apps/api/src/api/routes/workspaces.py::list_workspaces` includes `joined_at` for the API-key workspace response, matching the session-user response.
- `apps/api/src/services/workspaces.py::WorkspaceService.leave_workspace` rejects membership removal in single-workspace mode with the exact message `leaving is disabled in single-workspace mode`.
- `apps/web/src/pages/settings/profile/sections/WorkspacesSection.tsx` hides the leave action and displays the single-workspace restriction.
- `apps/web/src/contexts/WorkspaceContext.tsx` clears stale selected/active workspace state when the refreshed identity has zero workspaces.
- `apps/api/src/services/workspaces.py::WorkspaceService.accept_invitation` locks the invitation row, handles a concurrent membership uniqueness conflict, and caches ORM values before rollback recovery.
- `WorkspaceMember` now has the named composite uniqueness constraint `uq_workspace_members_workspace_id_user_id` in `apps/api/src/models/workspace.py`.
- Migration `apps/api/alembic/versions/b21f59d97f4c_prevent_duplicate_workspace_memberships.py` (`b21f59d97f4c`, down revision `0016`) removes existing duplicates deterministically before adding the unique invariant.
- Post-commit member-left event and audit publication failures are logged in `WorkspaceService.leave_workspace`; a durable membership deletion is not reported as a failed operation.
- `apps/api/src/services/serializers.py::_to_iso` normalizes stored timestamps to UTC-aware ISO values.
- The cascade test setup no longer inserts a duplicate owner membership that violates the new database invariant.

## Validation

- Focused final regression suite: **44 passed**, 60 warnings.
- Cascade regression rerun: **6 passed**, 3 warnings.
- Full `make api-test`: **315 passed, 10 skipped, 318 warnings** in 782.75 seconds.
- `make api-lint`: passed; `ruff check` clean and 155 files already formatted.
- `make db-check`: passed; one migration head and no model/migration drift.
- `make web-build`: passed; TypeScript check and Vite build succeeded. The existing large-chunk warning remains.
- `git diff --check`: passed.
- Alternate-port supervisor smoke test: passed. `API_PORT=18001` and `WEB_PORT=15174` reached both fake child processes, and SIGTERM cleanup left no child processes.

## Visual verification

The isolated stack used API `127.0.0.1:18000`, web `127.0.0.1:15173`, and a dedicated SQLite database. The unrelated default-port stack was not modified.

Obscura evidence captured during this run:

- Login page: `/tmp/visual186-login.png` (SHA-256 `895e157e492492e65d7685947b5cf7cbbc32c5d60459e8f72212e866154c37f0`).
- Security settings: `/tmp/visual186-security.png` (SHA-256 `8e7f67821eba9c1f6dd0574fc76a5f860a2ef8d9f65a3eeba025530077d50e1f`).
- Admin workspaces: `/tmp/visual186-workspaces.png` (SHA-256 `fcd665c1d0019171b8c21d5b5fb47ada5492cce975666c2d06ee1944c3e66aa7`).
- Member workspaces with leave actions: `/tmp/visual186-user1-workspaces.png` (SHA-256 `c46d60699ab2e57dc7a53931d06e49aefa403cc8f2bbab392a442c0ace1fb76c`).

Obscura required a test-only `tf_has_session` restore for authenticated fresh targets because its storage behavior differs from a normal browser. During one menu/navigation transition it reported `Failed to execute 'removeChild' on 'Node': The node to be removed is not a child of this node` in a Radix Select portal. The direct security target did not reproduce it. This was not classified as an application defect without a normal-browser reproduction; it remains a human follow-up item.

## Worktree hygiene

The worktree also contained pre-existing alternate-port edits in `AGENTS.md`, `Makefile`, `README.md`, `apps/web/vite.config.ts`, and `scripts/dev.py`. They were not part of the focused PR #186 fix set and were not staged in the follow-up commit.

## Disposition

The verified code and test findings are addressed locally. Any pushed follow-up commit is on the already-merged head branch and does not change the merged `main` result. No merge, close, approval, or PR finalization action was performed by this run.
