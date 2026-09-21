"""Central permission catalog. Roles hold a subset of these as a list of strings.

Convention: `<resource>:<action>`. `*` grants everything.
"""

WORKSPACE_READ = "workspace:read"
WORKSPACE_UPDATE = "workspace:update"
WORKSPACE_DELETE = "workspace:delete"

MEMBER_READ = "member:read"
MEMBER_INVITE = "member:invite"
MEMBER_MANAGE = "member:manage"  # change roles, remove members

ROLE_READ = "role:read"
ROLE_MANAGE = "role:manage"

APIKEY_READ = "apikey:read"
APIKEY_MANAGE = "apikey:manage"

NOTIFICATION_READ = "notification:read"
NOTIFICATION_ACK = "notification:acknowledge"

MESSAGE_READ = "message:read"
MESSAGE_SEND = "message:send"

JOB_VIEW = "jobs:view"
JOB_EDIT = "jobs:edit"

WEBHOOK_READ = "webhook:read"
WEBHOOK_MANAGE = "webhook:manage"

AUDIT_READ = "audit:read"

PERMISSION_DEFINITIONS: dict[str, dict[str, str]] = {
    WORKSPACE_READ: {"resource": "workspace", "action": "read"},
    WORKSPACE_UPDATE: {"resource": "workspace", "action": "update"},
    WORKSPACE_DELETE: {"resource": "workspace", "action": "delete"},
    MEMBER_READ: {"resource": "member", "action": "read"},
    MEMBER_INVITE: {"resource": "member", "action": "invite"},
    MEMBER_MANAGE: {"resource": "member", "action": "manage"},
    ROLE_READ: {"resource": "role", "action": "read"},
    ROLE_MANAGE: {"resource": "role", "action": "manage"},
    APIKEY_READ: {"resource": "apikey", "action": "read"},
    APIKEY_MANAGE: {"resource": "apikey", "action": "manage"},
    NOTIFICATION_READ: {"resource": "notification", "action": "read"},
    NOTIFICATION_ACK: {"resource": "notification", "action": "acknowledge"},
    MESSAGE_READ: {"resource": "message", "action": "read"},
    MESSAGE_SEND: {"resource": "message", "action": "send"},
    JOB_VIEW: {"resource": "jobs", "action": "view"},
    JOB_EDIT: {"resource": "jobs", "action": "edit"},
    WEBHOOK_READ: {"resource": "webhook", "action": "read"},
    WEBHOOK_MANAGE: {"resource": "webhook", "action": "manage"},
    AUDIT_READ: {"resource": "audit", "action": "read"},
}

ALL_PERMISSIONS = list(PERMISSION_DEFINITIONS)


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
                APIKEY_MANAGE,
                NOTIFICATION_READ,
                NOTIFICATION_ACK,
                MESSAGE_READ,
                MESSAGE_SEND,
            ]
        case "viewer":
            return [
                WORKSPACE_READ,
                MEMBER_READ,
                ROLE_READ,
                APIKEY_READ,
                APIKEY_MANAGE,
                NOTIFICATION_READ,
                NOTIFICATION_ACK,
                MESSAGE_READ,
                MESSAGE_SEND,
            ]
        case _:
            raise ValueError(f"unknown role {role_name}")
