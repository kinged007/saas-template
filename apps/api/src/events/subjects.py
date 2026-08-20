from enum import StrEnum


class EventBusDriver(StrEnum):
    INPROCESS = "inprocess"
    NATS = "nats"


class Subjects:
    """NATS-style subject namespaces for domain events.

    Contract:
    - Durable subjects (default) are persisted to the JetStream stream and
      processed by exactly one deployment via a load-balanced durable
      consumer. Every durable subject MUST have exactly one durable
      workflow subscribed, otherwise messages accumulate in the stream.
    - Transient subjects are published over core NATS only (no persistence).
      They exist for realtime fan-out (every replica receives the event) or
      for events that nothing consumes yet. Durable subscriptions on a
      transient subject are rejected by the NATS bus.
    """

    NOTIFICATIONS = "notifications"
    NOTIFICATIONS_CREATED = "notifications.created"

    WORKSPACES = "workspaces"
    WORKSPACE_CREATED = "workspaces.created"
    WORKSPACE_INVITATION_CREATED = "workspaces.invitation.created"
    WORKSPACE_MEMBER_INVITED = "workspaces.member.invited"
    WORKSPACE_MEMBER_JOINED = "workspaces.member.joined"
    WORKSPACE_MEMBER_ROLE_CHANGED = "workspaces.member.role_changed"
    WORKSPACE_MEMBER_REMOVED = "workspaces.member.removed"

    APIKEYS = "apikeys"
    APIKEY_CREATED = "apikeys.created"
    APIKEY_REVOKED = "apikeys.revoked"

    AUDIT = "audit"
    AUDIT_ENTRY_CREATED = "audit.entry.created"


# Subjects published over core NATS (realtime fan-out / publish-only).
# TODO(events): when a durable consumer is added for one of these, move the
# subject into the durable set and switch its publisher to transient=False.
TRANSIENT_SUBJECTS: set[str] = {
    Subjects.NOTIFICATIONS_CREATED,
}


ALL = [
    Subjects.NOTIFICATIONS_CREATED,
    Subjects.WORKSPACE_CREATED,
    Subjects.WORKSPACE_INVITATION_CREATED,
    Subjects.WORKSPACE_MEMBER_INVITED,
    Subjects.WORKSPACE_MEMBER_JOINED,
    Subjects.WORKSPACE_MEMBER_ROLE_CHANGED,
    Subjects.WORKSPACE_MEMBER_REMOVED,
    Subjects.APIKEY_CREATED,
    Subjects.APIKEY_REVOKED,
    Subjects.AUDIT_ENTRY_CREATED,
]
