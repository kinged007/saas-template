/** Mirror of the backend permission catalog (core/permissions.py).

Notification scopes (`notification:read` / `notification:update`) are
API-key-only: session users always access their own notifications, keys
must list the scope to use notification routes.
*/
export const ALL_PERMISSIONS = [
  "workspace:read",
  "workspace:update",
  "workspace:delete",
  "member:read",
  "member:create",
  "member:update",
  "member:delete",
  "role:read",
  "role:create",
  "apikey:read",
  "apikey:create",
  "apikey:delete",
  "message:read",
  "message:create",
  "jobs:read",
  "jobs:update",
  "webhook:read",
  "webhook:create",
  "webhook:update",
  "webhook:delete",
  "audit:read",
];

export const KEY_ONLY_PERMISSIONS = ["notification:read", "notification:update"];
