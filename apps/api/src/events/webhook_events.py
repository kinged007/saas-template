"""Public event names available for outbound webhook subscriptions.

Product code publishes internal bus subjects (`src.events.Subjects`); this
module maps a stable public name to each deliverable subject so subscribers
see a versioned contract (`workspaces.created`, ...) instead of bus internals.
New event types register via `@register_webhook_event`.
"""

from __future__ import annotations

from src.events.subjects import Subjects

_REGISTRY: dict[str, str] = {}


def register_webhook_event(name: str, subject: str) -> str:
    """Register public event `name` for bus `subject`. Returns the name."""
    if name in _REGISTRY and _REGISTRY[name] != subject:
        raise ValueError(f"webhook event {name!r} already registered")
    _REGISTRY[name] = subject
    return name


def webhook_event_subject(name: str) -> str | None:
    return _REGISTRY.get(name)


def webhook_event_names() -> list[str]:
    return sorted(_REGISTRY)


def webhook_subject_events() -> dict[str, list[str]]:
    """Bus subject → public names subscribed to it (fan-out lookup)."""
    out: dict[str, list[str]] = {}
    for name, subject in _REGISTRY.items():
        out.setdefault(subject, []).append(name)
    return out


# Seed: durable domain subjects only. Transient fan-out subjects
# (notifications.created, message.live, renamed) and the internal
# jobs.execute subject are excluded from v1.
for _name, _subject in [
    ("workspaces.created", Subjects.WORKSPACE_CREATED),
    ("member.invited", Subjects.WORKSPACE_MEMBER_INVITED),
    ("member.joined", Subjects.WORKSPACE_MEMBER_JOINED),
    ("member.role_changed", Subjects.WORKSPACE_MEMBER_ROLE_CHANGED),
    ("member.removed", Subjects.WORKSPACE_MEMBER_REMOVED),
    ("invitation.created", Subjects.WORKSPACE_INVITATION_CREATED),
    ("apikeys.created", Subjects.APIKEY_CREATED),
    ("apikeys.revoked", Subjects.APIKEY_REVOKED),
    ("audit.entry.created", Subjects.AUDIT_ENTRY_CREATED),
    ("conversations.created", Subjects.CONVERSATION_CREATED),
    ("conversations.message.created", Subjects.CONVERSATION_MESSAGE_CREATED),
]:
    register_webhook_event(_name, _subject)

del _name, _subject
