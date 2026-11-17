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
    source_event_id: str | None = None,
) -> dict:
    """Shape of an `audit.entry.created` event payload (consumed by the audit
    workflow, which persists an AuditLogEntry row).

    `source_event_id` is the id of the event this entry was derived from. The
    audit workflow dedupes on it, so an audit entry produced by a subscriber
    handler must pass the *inbound* event's id — the handler, not the audit
    publish, is what re-runs on a JetStream redelivery. Direct producers omit
    it and the audit envelope's own id is used.
    """
    payload = {
        "workspace_id": workspace_id,
        "actor_user_id": actor_user_id,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
        "details": details or {},
        "ip_address": ip_address,
    }
    if source_event_id:
        payload["source_event_id"] = source_event_id
    return payload


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
