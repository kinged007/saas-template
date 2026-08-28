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

ALL_PERMISSIONS = [
    WORKSPACE_READ,
    WORKSPACE_UPDATE,
    WORKSPACE_DELETE,
    MEMBER_READ,
    MEMBER_INVITE,
    MEMBER_MANAGE,
    ROLE_READ,
    ROLE_MANAGE,
    APIKEY_READ,
    APIKEY_MANAGE,
    NOTIFICATION_READ,
    NOTIFICATION_ACK,
    MESSAGE_READ,
    MESSAGE_SEND,
    JOB_VIEW,
    JOB_EDIT,
]


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
