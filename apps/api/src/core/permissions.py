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

ROLE_READ = "role:read"
ROLE_CREATE = "role:create"  # create + update custom roles

APIKEY_READ = "apikey:read"
APIKEY_CREATE = "apikey:create"  # mint keys (capped by creator's own permissions)
APIKEY_DELETE = "apikey:delete"  # quota changes + revoke

NOTIFICATION_READ = "notification:read"
NOTIFICATION_UPDATE = "notification:update"

MESSAGE_READ = "message:read"
MESSAGE_CREATE = "message:create"  # start conversations, send messages, rename

JOB_READ = "jobs:read"
JOB_UPDATE = "jobs:update"  # modify or trigger

WEBHOOK_READ = "webhook:read"
WEBHOOK_CREATE = "webhook:create"  # subscribe
WEBHOOK_UPDATE = "webhook:update"  # update, rotate secret, redeliver
WEBHOOK_DELETE = "webhook:delete"  # unsubscribe

AUDIT_READ = "audit:read"

# API-key-only scopes: never granted to roles, never required of sessions.
# Declared before PERMISSION_DEFINITIONS so ALL_PERMISSIONS can exclude them.
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
    ROLE_READ: {"resource": "role", "action": "read"},
    ROLE_CREATE: {"resource": "role", "action": "create"},
    APIKEY_READ: {"resource": "apikey", "action": "read"},
    APIKEY_CREATE: {"resource": "apikey", "action": "create"},
    APIKEY_DELETE: {"resource": "apikey", "action": "delete"},
    MESSAGE_READ: {"resource": "message", "action": "read"},
    MESSAGE_CREATE: {"resource": "message", "action": "create"},
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

NOTIFICATION_PERMISSIONS = {NOTIFICATION_READ, NOTIFICATION_UPDATE}


def register_permission(permission: str, *, resource: str, action: str) -> str:
    """Register a permission a new service needs, e.g. `register_permission(
    "billing:read", resource="billing", action="read")` at import time.

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
    """Default permission set per seeded system role."""
    all_ = set(ALL_PERMISSIONS)
    match role_name:
        case "owner":
            return [*all_, "*"]
        case "admin":
            # everything except deleting the workspace itself
            return [p for p in all_ if p not in {WORKSPACE_DELETE}]
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
