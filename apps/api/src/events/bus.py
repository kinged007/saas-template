from __future__ import annotations

import logging
import uuid
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

logger = logging.getLogger(__name__)

# A subscriber handler: (payload dict, metadata) -> None
SubscriberHandler = Callable[[dict, "EventMetadata"], Awaitable[None]]


@dataclass
class EventMetadata:
    subject: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "event_id": self.event_id,
            "correlation_id": self.correlation_id,
            "occurred_at": self.occurred_at,
        }


@dataclass
class EventEnvelope:
    metadata: EventMetadata
    payload: dict


class EventBus(ABC):
    """Publish/subscribe contract for domain events.

    Development uses the in-process implementation; production uses NATS
    JetStream. Workflows only depend on this interface.
    """

    @abstractmethod
    async def publish(
        self, subject: str, payload: dict, *, correlation_id: str | None = None
    ) -> None:
        """Publish an event to a subject."""

    @abstractmethod
    async def subscribe(
        self, subject: str, handler: SubscriberHandler, *, fanout: bool = False
    ) -> str:
        """Subscribe a handler to a subject (or wildcard). Returns subscription id.

        `fanout=True` marks the subscription as realtime fan-out: every bus
        instance receives the event (used to push WebSocket events in every
        replica). Default (durable) subscriptions are load-balanced across
        instances via JetStream consumers / queue groups.
        """

    @abstractmethod
    async def unsubscribe(self, subscription_id: str) -> None: ...

    @abstractmethod
    async def start(self) -> None:
        """Connect and begin consuming for all registered subscriptions."""

    @abstractmethod
    async def stop(self) -> None:
        """Gracefully stop and disconnect."""

    @property
    @abstractmethod
    def name(self) -> str: ...


class PublishError(Exception):
    pass


class SubscriptionError(Exception):
    pass
