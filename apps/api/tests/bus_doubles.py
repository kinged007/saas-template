"""Test doubles for the event bus.

RecordingBus implements the EventBus contract but only records publishes — it
never delivers. It lets service unit tests assert exactly which subjects,
payloads, correlation ids and transient flags a service emits without wiring
up a live bus or waiting on async delivery.
"""

from __future__ import annotations

from src.events.bus import EventBus


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
