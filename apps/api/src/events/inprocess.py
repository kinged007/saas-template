from __future__ import annotations

import asyncio
import logging

from src.events.bus import (
    EventBus,
    EventEnvelope,
    EventMetadata,
    SubscriberHandler,
)

logger = logging.getLogger(__name__)


def _subject_matches(subscription: str, subject: str) -> bool:
    """Support NATS-style wildcards: '*' single token, '>' rest."""
    sub_tokens = subscription.split(".")
    subj_tokens = subject.split(".")
    for i, tok in enumerate(sub_tokens):
        if tok == ">":
            return True
        if i >= len(subj_tokens):
            return False
        if tok != "*" and tok != subj_tokens[i]:
            return False
    return len(sub_tokens) == len(subj_tokens)


class InProcessEventBus(EventBus):
    """Development event bus: async in-process pub/sub.

    Deliveries are enqueued per subscription so a slow handler never blocks
    publishers. Subscribers registered *before* start() will receive events.
    """

    name = "inprocess"

    def __init__(self) -> None:
        self._handlers: dict[str, SubscriberHandler] = {}
        self._queues: dict[str, asyncio.Queue] = {}
        self._tasks: list[asyncio.Task] = []
        self._started = False

    async def publish(
        self, subject: str, payload: dict, *, correlation_id: str | None = None
    ) -> None:
        envelope = EventEnvelope(
            metadata=EventMetadata(subject=subject, correlation_id=correlation_id or ""),
            payload=payload,
        )
        if not self._started:
            # Buffered until start(): events published during startup are kept.
            pass
        for sub, queue in list(self._queues.items()):
            if _subject_matches(sub, subject):
                queue.put_nowait(envelope)
        logger.debug("published %s (%d subscribers)", subject, len(self._queues))

    async def subscribe(
        self, subject: str, handler: SubscriberHandler, *, fanout: bool = False
    ) -> str:
        # Idempotent: re-registration (e.g. app restart, repeated lifespans)
        # replaces the previous handler for the same subject.
        if subject in self._handlers:
            logger.warning("replacing existing handler for %s", subject)
        subscription_id = f"{subject}:{len(self._handlers)}"
        self._handlers[subject] = handler
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        self._queues[subject] = queue
        if self._started:
            self._tasks.append(asyncio.create_task(self._consume(subscription_id, queue, handler)))
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> None:
        subject, _ = subscription_id.rsplit(":", 1)
        self._handlers.pop(subject, None)
        self._queues.pop(subject, None)

    async def start(self) -> None:
        self._started = True
        for subscription_id, queue, handler in self._pairs():
            self._tasks.append(asyncio.create_task(self._consume(subscription_id, queue, handler)))
        logger.info("in-process event bus started")

    async def stop(self) -> None:
        self._started = False
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks.clear()

    def _pairs(self):
        return [
            (f"{subject}:{i}", queue, handler)
            for i, (subject, handler) in enumerate(self._handlers.items())
            for queue in [self._queues[subject]]
        ]

    async def _consume(
        self, subscription_id: str, queue: asyncio.Queue[EventEnvelope], handler: SubscriberHandler
    ) -> None:
        logger.debug("subscriber %s consuming", subscription_id)
        while True:
            envelope = await queue.get()
            try:
                await handler(envelope.payload, envelope.metadata)
            except Exception:
                logger.exception(
                    "subscriber %s failed for %s", subscription_id, envelope.metadata.subject
                )
            finally:
                queue.task_done()
