"""Central permission catalog. Roles hold a subset of these as a list of strings.

Convention: `<resource>:<action>`, with actions limited to
`create | read | update | delete`. `*` grants everything.

Notifications are user-scoped, not permission-scoped: session users always
access their own notifications. `notification:read` / `notification:update`
exist only as API-key gates, so keys must opt in to read or delete notifications.
"""

WORKSPACE_READ = "workspace:read"
WORKSPACE_UPDATE = "workspace:update"
WORKSPACE_DELETE = "workspace:delete"

MEMBER_READ = "member:read"
MEMBER_CREATE = "member:create"  # invite
MEMBER_UPDATE = "member:update"  # change roles
MEMBER_DELETE = "member:delete"  # remove members, revoke invitations

# Edit another member's profile, notifications and security. Distinct from
# `member:update` so holding it never implies role changes or removal.
PROFILE_UPDATE = "profile:update"

ROLE_READ = "role:read"
ROLE_CREATE = "role:create"  # create + update custom roles

APIKEY_READ = "apikey:read"
APIKEY_CREATE = "apikey:create"  # mint keys (capped by creator's own permissions)
APIKEY_DELETE = "apikey:delete"  # quota changes + revoke

NOTIFICATION_READ = "notification:read"
NOTIFICATION_UPDATE = "notification:update"

MESSAGE_READ = "message:read"
MESSAGE_CREATE = "message:create"  # start conversations, send messages, rename
MESSAGE_UPDATE = "message:update"  # edit a conversation's participants

JOB_READ = "jobs:read"
JOB_UPDATE = "jobs:update"  # modify or trigger

WEBHOOK_READ = "webhook:read"
WEBHOOK_CREATE = "webhook:create"  # subscribe
WEBHOOK_UPDATE = "webhook:update"  # update, rotate secret, redeliver
WEBHOOK_DELETE = "webhook:delete"  # unsubscribe

AUDIT_READ = "audit:read"

# API-key-only scopes: never granted to roles, never required of sessions.
# Declared before PERMISSION_DEFINITIONS so ALL_PERMISSIONS can exclude them.
#
# GET /api-keys/effective-permissions offers them to every member with
# `apikey:read`, not owners only: they are user-scoped, so a key reaches
# nothing its own creator could not already reach with their session.
KEY_ONLY_PERMISSIONS = frozenset({NOTIFICATION_READ, NOTIFICATION_UPDATE})

PERMISSION_DEFINITIONS: dict[str, dict[str, str]] = {
    # Key-only scopes stay registered so route-guard references resolve,
    # but they are NOT assignable to roles (see ALL_PERMISSIONS).
    NOTIFICATION_READ: {"resource": "notification", "action": "read"},
    NOTIFICATION_UPDATE: {"resource": "notification", "action": "update"},
    WORKSPACE_READ: {"resource": "workspace", "action": "read"},
    WORKSPACE_UPDATE: {"resource": "workspace", "action": "update"},
    WORKSPACE_DELETE: {"resource": "workspace", "action": "delete"},
    MEMBER_READ: {"resource": "member", "action": "read"},
    MEMBER_CREATE: {"resource": "member", "action": "create"},
    MEMBER_UPDATE: {"resource": "member", "action": "update"},
    MEMBER_DELETE: {"resource": "member", "action": "delete"},
    PROFILE_UPDATE: {"resource": "profile", "action": "update"},
    ROLE_READ: {"resource": "role", "action": "read"},
    ROLE_CREATE: {"resource": "role", "action": "create"},
    APIKEY_READ: {"resource": "apikey", "action": "read"},
    APIKEY_CREATE: {"resource": "apikey", "action": "create"},
    APIKEY_DELETE: {"resource": "apikey", "action": "delete"},
    MESSAGE_READ: {"resource": "message", "action": "read"},
    MESSAGE_CREATE: {"resource": "message", "action": "create"},
    MESSAGE_UPDATE: {"resource": "message", "action": "update"},
    JOB_READ: {"resource": "jobs", "action": "read"},
    JOB_UPDATE: {"resource": "jobs", "action": "update"},
    WEBHOOK_READ: {"resource": "webhook", "action": "read"},
    WEBHOOK_CREATE: {"resource": "webhook", "action": "create"},
    WEBHOOK_UPDATE: {"resource": "webhook", "action": "update"},
    WEBHOOK_DELETE: {"resource": "webhook", "action": "delete"},
    AUDIT_READ: {"resource": "audit", "action": "read"},
}

# Assignable through roles / the permission-catalog endpoint. Notification
# scopes stay out: they gate API keys only.
ALL_PERMISSIONS = [p for p in PERMISSION_DEFINITIONS if p not in KEY_ONLY_PERMISSIONS]

# Full registry including key-only scopes (for API-key validation).
ALL_PERMISSIONS_INCLUDING_KEY_ONLY = [*ALL_PERMISSIONS, NOTIFICATION_READ, NOTIFICATION_UPDATE]


def register_permission(permission: str, *, resource: str, action: str) -> str:
    """Register a permission a new service needs, e.g. `register_permission(
    "billing:read", resource="billing", action="read")` at import time.

    New permissions land in the role-assignable registry. If a future scope
    must be API-key-only, add it to KEY_ONLY_PERMISSIONS explicitly and gate
    roles against it — registration alone does not make that decision.

    The single catalog endpoint serves the result, so the roles UI picks the
    new permission up without a frontend change. Re-registering the same
    value is a no-op (idempotent at import); conflicting resource/action
    for an existing value raises."""
    existing = PERMISSION_DEFINITIONS.get(permission)
    if existing is not None:
        if existing != {"resource": resource, "action": action}:
            raise ValueError(f"permission {permission} already registered")
        return permission
    PERMISSION_DEFINITIONS[permission] = {"resource": resource, "action": action}
    ALL_PERMISSIONS.append(permission)
    ALL_PERMISSIONS_INCLUDING_KEY_ONLY.append(permission)
    return permission


def permissions_for_role(role_name: str) -> list[str]:
    """Default permission set per seeded system role.

    Built from `ALL_PERMISSIONS` itself, not a set of it: the declaration order
    is what a stored row (and so `/roles`, `/auth/me`) reports, and it is stable
    across processes — a set's iteration order is hash-randomized per process.
    """
    match role_name:
        case "owner":
            return [*ALL_PERMISSIONS, "*"]
        case "admin":
            # everything except deleting the workspace itself. Adding a
            # capability here also grants it to every existing unedited admin
            # role at the next boot (sync_system_role_permissions), so a
            # takeover-capable scope like profile:update needs a callout.
            return [p for p in ALL_PERMISSIONS if p not in {WORKSPACE_DELETE}]
        case "editor":
            return [
                WORKSPACE_READ,
                MEMBER_READ,
                ROLE_READ,
                APIKEY_READ,
                APIKEY_CREATE,
                APIKEY_DELETE,
                MESSAGE_READ,
                MESSAGE_CREATE,
                MESSAGE_UPDATE,
            ]
        case "viewer":
            return [
                WORKSPACE_READ,
                MEMBER_READ,
                ROLE_READ,
                APIKEY_READ,
                APIKEY_CREATE,
                APIKEY_DELETE,
                MESSAGE_READ,
                MESSAGE_CREATE,
            ]
        case _:
            raise ValueError(f"unknown role {role_name}")
