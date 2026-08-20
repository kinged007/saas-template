from __future__ import annotations

import asyncio
import logging
import uuid

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
    publishers. Subscribers registered *before* start() will receive events;
    publishes issued before start() are buffered in the per-subscription
    queues and delivered once start() spawns the consumer tasks.

    Lifecycle semantics:
    - `start()` may be called once per run (idempotent); buffered publishes
      are delivered after it returns.
    - `unsubscribe()` cancels the consumer task; re-registering the same
      subject replaces the handler and cancels the stale task.
    - `stop()` cancels all consumer tasks; publishes after stop are dropped
      with a warning.
    """

    name = "inprocess"

    def __init__(self) -> None:
        self._handlers: dict[str, SubscriberHandler] = {}
        self._queues: dict[str, asyncio.Queue[EventEnvelope]] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._started = False
        self._stopped = False

    async def publish(
        self,
        subject: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        transient: bool = False,
    ) -> None:
        if self._stopped:
            logger.warning("dropping publish to %s: bus is stopped", subject)
            return
        envelope = EventEnvelope(
            metadata=EventMetadata(subject=subject, correlation_id=correlation_id or ""),
            payload=payload,
        )
        matched = 0
        for sub, queue in list(self._queues.items()):
            if _subject_matches(sub, subject):
                queue.put_nowait(envelope)
                matched += 1
        logger.debug("published %s (%d subscriber queues)", subject, matched)

    async def subscribe(
        self, subject: str, handler: SubscriberHandler, *, fanout: bool = False
    ) -> str:
        stale = self._tasks.pop(subject, None)
        if stale is not None:
            stale.cancel()
            logger.warning("replacing existing handler for %s", subject)
        self._handlers[subject] = handler
        self._queues[subject] = asyncio.Queue()
        subscription_id = f"{subject}:{uuid.uuid4().hex[:8]}"
        if self._started:
            self._tasks[subject] = asyncio.create_task(
                self._consume(subject, self._queues[subject], handler)
            )
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> None:
        subject, _ = subscription_id.rsplit(":", 1)
        self._handlers.pop(subject, None)
        self._queues.pop(subject, None)
        task = self._tasks.pop(subject, None)
        if task is not None:
            task.cancel()

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._stopped = False
        for subject, handler in self._handlers.items():
            self._tasks[subject] = asyncio.create_task(
                self._consume(subject, self._queues[subject], handler)
            )
        logger.info("in-process event bus started (%d subscriptions)", len(self._tasks))

    async def stop(self) -> None:
        self._started = False
        self._stopped = True
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _consume(
        self, subject: str, queue: asyncio.Queue[EventEnvelope], handler: SubscriberHandler
    ) -> None:
        logger.debug("subscriber %s consuming", subject)
        while True:
            envelope = await queue.get()
            try:
                await handler(envelope.payload, envelope.metadata)
            except Exception:
                logger.exception("subscriber %s failed for %s", subject, envelope.metadata.subject)
            finally:
                queue.task_done()
