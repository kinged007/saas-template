from enum import StrEnum


class EventBusDriver(StrEnum):
    INPROCESS = "inprocess"
    NATS = "nats"


class Subjects:
    """NATS-style subject namespaces for domain events."""

    NOTIFICATIONS = "notifications"
    NOTIFICATIONS_CREATED = "notifications.created"
    WORKSPACES = "workspaces"
    WORKSPACE_MEMBER_INVITED = "workspaces.member.invited"
    WORKSPACE_MEMBER_JOINED = "workspaces.member.joined"


ALL = [
    Subjects.NOTIFICATIONS_CREATED,
    Subjects.WORKSPACE_MEMBER_INVITED,
    Subjects.WORKSPACE_MEMBER_JOINED,
]
