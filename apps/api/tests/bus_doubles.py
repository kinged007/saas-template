"""Test doubles for the event bus.

RecordingBus implements the EventBus contract but only records publishes — it
never delivers. It lets service unit tests assert exactly which subjects,
payloads, correlation ids and transient flags a service emits without wiring
up a live bus or waiting on async delivery.

ReplayBus delivers synchronously and can redeliver an already-delivered
envelope, which is how a test reproduces JetStream's at-least-once delivery.
"""

from __future__ import annotations

from src.db.session import SessionFactory
from src.events.bus import (
    EventBus,
    EventEnvelope,
    EventMetadata,
    SubscriberHandler,
    subject_matches,
)
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

    async def wait_idle(self) -> None:
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


class ReplayBus(EventBus):
    """Delivers to subscribed handlers inline and can redeliver an envelope.

    JetStream is at-least-once: a nack, an ack timeout or a consumer restart
    hands the *same* envelope to the handler again, metadata included.
    `publish` cannot model that — the in-process bus mints a fresh event_id per
    publish — so redelivery goes through `redeliver`, which re-invokes the
    handlers with the metadata of the last publish on that subject.
    """

    name = "replay"

    def __init__(self) -> None:
        self._handlers: dict[str, list[SubscriberHandler]] = {}
        self._delivered: dict[str, EventEnvelope] = {}
        self._subjects_by_id: dict[str, str] = {}

    async def publish(
        self,
        subject: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        transient: bool = False,
    ) -> None:
        envelope = EventEnvelope(
            metadata=EventMetadata(subject=subject, correlation_id=correlation_id or ""),
            payload=payload,
        )
        self._delivered[subject] = envelope
        await self._deliver(subject, envelope)

    async def redeliver(self, subject: str) -> None:
        await self._deliver(subject, self._delivered[subject])

    async def _deliver(self, subject: str, envelope: EventEnvelope) -> None:
        for subscription, handlers in list(self._handlers.items()):
            if subject_matches(subscription, subject):
                for handler in list(handlers):
                    await handler(envelope.payload, envelope.metadata)

    async def subscribe(self, subject: str, handler, *, fanout: bool = False) -> str:
        subscription_id = f"{subject}:sub{len(self._subjects_by_id)}"
        self._subjects_by_id[subscription_id] = subject
        self._handlers.setdefault(subject, []).append(handler)
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> None:
        subject = self._subjects_by_id.pop(subscription_id, None)
        if subject is not None:
            self._handlers.pop(subject, None)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass

    async def wait_idle(self) -> None:
        # Delivery is inline in publish(), so the bus is always idle.
        pass
