"""Publishing helpers for services.

Services never construct envelopes or subject strings themselves — they call
`publish_event` for domain events and `publish_audit` for audit trail events,
which keeps the audit payload contract in one place.
"""

from __future__ import annotations

from src.events.bus import EventBus
from src.events.subjects import Subjects


async def publish_event(
    bus: EventBus | None,
    subject: str,
    payload: dict,
    *,
    correlation_id: str | None = None,
    transient: bool = False,
) -> None:
    """Publish a domain event, no-op when the service has no bus wired."""
    if bus is None:
        return
    await bus.publish(subject, payload, correlation_id=correlation_id, transient=transient)


def audit_payload(
    *,
    workspace_id: str | None,
    resource_type: str,
    resource_id: str,
    action: str,
    actor_user_id: str | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> dict:
    """Shape of an `audit.entry.created` event payload (consumed by the audit
    workflow, which persists an AuditLogEntry row)."""
    return {
        "workspace_id": workspace_id,
        "actor_user_id": actor_user_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
        "details": details or {},
        "ip_address": ip_address,
    }


async def publish_audit(
    bus: EventBus | None,
    *,
    correlation_id: str | None = None,
    **kwargs,
) -> None:
    """Publish an audit trail event; no-op when the service has no bus wired."""
    await publish_event(
        bus,
        Subjects.AUDIT_ENTRY_CREATED,
        audit_payload(**kwargs),
        correlation_id=correlation_id,
    )
