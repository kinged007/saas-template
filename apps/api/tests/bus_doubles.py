"""Test doubles for the event bus.

RecordingBus implements the EventBus contract but only records publishes — it
never delivers. It lets service unit tests assert exactly which subjects,
payloads, correlation ids and transient flags a service emits without wiring
up a live bus or waiting on async delivery.
"""

from __future__ import annotations

from src.db.session import SessionFactory
from src.events.bus import EventBus
from src.events.subjects import Subjects
from src.models.core import Invitation


class RecordingBus(EventBus):
    name = "recording"

    def __init__(self) -> None:
        self.events: list[tuple[str, dict, str | None, bool]] = []
        self.subscribed: list[tuple[str, bool]] = []
        self.unsubscribed: list[str] = []

    async def publish(
        self,
        subject: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        transient: bool = False,
    ) -> None:
        self.events.append((subject, payload, correlation_id, transient))

    async def subscribe(self, subject: str, handler, *, fanout: bool = False) -> str:
        self.subscribed.append((subject, fanout))
        return f"{subject}:sub"

    async def unsubscribe(self, subscription_id: str) -> None:
        self.unsubscribed.append(subscription_id)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    def by_subject(self, subject: str) -> list[tuple[dict, str | None, bool]]:
        return [(p, c, t) for s, p, c, t in self.events if s == subject]

    def audit(self) -> list[tuple[dict, str | None, bool]]:
        return self.by_subject("audit.entry.created")

    def actions(self) -> list[str]:
        return [payload["action"] for payload, _, _ in self.audit()]


class CommitProbeBus(RecordingBus):
    """RecordingBus that snapshots committed invitation state at publish time.

    `invitation.created` carries no token, so the only token a handler can use
    is whatever it re-reads from the row — which means the publishing service
    must commit before it publishes. This double opens an independent session
    inside `publish` and records the token durably committed at that instant, so
    a service that publishes first shows up as `None` (row not yet visible) or
    as the pre-rotation token.

    ponytail: probes only `invitation.created`; widen the subject list if another
    event ever needs the same ordering guarantee.
    """

    name = "commit-probe"

    def __init__(self) -> None:
        super().__init__()
        self.committed_token_at_publish: list[str | None] = []

    async def publish(
        self,
        subject: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        transient: bool = False,
    ) -> None:
        if subject == Subjects.WORKSPACE_INVITATION_CREATED:
            async with SessionFactory() as probe:
                invite = await probe.get(Invitation, payload.get("invitation_id"))
                self.committed_token_at_publish.append(invite.token if invite else None)
        await super().publish(subject, payload, correlation_id=correlation_id, transient=transient)
