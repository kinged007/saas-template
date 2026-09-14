"""Public webhook event registry: bus subject → external event name.

Product code registers new deliverable event types here (via
`@register_webhook_event`) instead of scattering subject strings through the
webhook fan-out. Only durable domain subjects are registered: transient
fan-out subjects (realtime-only, no persistence) and the internal
`jobs.execute` control subject are excluded from v1.
"""

from __future__ import annotations

from src.events.subjects import Subjects

# public event name → bus subject
_WEBHOOK_EVENTS: dict[str, str] = {}

def register_webhook_event(event_name: str, subject: str) -> str:
    """Register one deliverable event type. Returns the event name."""
    _WEBHOOK_EVENTS[event_name] = subject
    return event_name

def webhook_event_names() -> list[str]:
    return sorted(_WEBHOOK_EVENTS)

def webhook_subject_for(event_name: str) -> str | None:
    return _WEBHOOK_EVENTS.get(event_name)

def webhook_event_for_subject(subject: str) -> str | None:
    for name, subj in _WEBHOOK_EVENTS.items():
        if subj == subject:
            return name
    return None

def webhook_subjects() -> list[str]:
    return sorted(set(_WEBHOOK_EVENTS.values()))

register_webhook_event("workspace.created", Subjects.WORKSPACE_CREATED)
register_webhook_event("invitation.created", Subjects.WORKSPACE_INVITATION_CREATED)
register_webhook_event("member.invited", Subjects.WORKSPACE_MEMBER_INVITED)
register_webhook_event("member.joined", Subjects.WORKSPACE_MEMBER_JOINED)
register_webhook_event("member.role_changed", Subjects.WORKSPACE_MEMBER_ROLE_CHANGED)
register_webhook_event("member.removed", Subjects.WORKSPACE_MEMBER_REMOVED)
register_webhook_event("apikey.created", Subjects.APIKEY_CREATED)
register_webhook_event("apikey.revoked", Subjects.APIKEY_REVOKED)
register_webhook_event("audit.entry.created", Subjects.AUDIT_ENTRY_CREATED)
register_webhook_event("conversation.message.created", Subjects.CONVERSATION_MESSAGE_CREATED)
