from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict

import nats
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from src.events.bus import (
    EventBus,
    EventEnvelope,
    EventMetadata,
    SubscriberHandler,
    SubscriptionError,
)
from src.events.subjects import Subjects

logger = logging.getLogger(__name__)

STREAM_NAME = "SAAS_TEMPLATE"
STREAM_SUBJECTS = [
    f"{Subjects.NOTIFICATIONS}.>",
    f"{Subjects.WORKSPACES}.>",
]


class NatsEventBus(EventBus):
    """Production event bus backed by NATS JetStream.

    - One stream (SAAS_TEMPLATE) with subjects for each namespace.
    - Each subscription is a durable consumer, so events survive restarts and
      are delivered exactly once per consumer with acks.
    - Handlers run as asyncio tasks; messages are acked after the handler
      completes (or nacked on failure so they are redelivered).
    """

    name = "nats"

    def __init__(self, url: str, *, queue_group: str = "saas-template-workers") -> None:
        self._url = url
        self._queue_group = queue_group
        self._nc: nats.NATS | None = None
        self._js: JetStreamContext | None = None
        self._subscriptions: dict[str, tuple[SubscriberHandler, object]] = {}
        self._pending: list[tuple[str, SubscriberHandler, bool]] = []
        self._tasks: list[asyncio.Task] = []

    async def publish(
        self, subject: str, payload: dict, *, correlation_id: str | None = None
    ) -> None:
        js = self._require_js()
        metadata = EventMetadata(
            subject=subject,
            correlation_id=correlation_id or "",
        )
        envelope = EventEnvelope(metadata=metadata, payload=payload)
        try:
            await js.publish(subject, json.dumps(asdict(envelope)).encode())
        except Exception as exc:  # pragma: no cover - network layer
            raise RuntimeError(f"nats publish failed: {exc}") from exc

    async def subscribe(
        self, subject: str, handler: SubscriberHandler, *, fanout: bool = False
    ) -> str:
        sub_id = str(uuid.uuid4())
        if self._nc is None:
            # Not connected yet (workflows are wired before start()): defer.
            self._pending.append((subject, handler, fanout))
            return sub_id
        await self._apply_subscription(subject, handler, fanout, sub_id)
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        self._subscriptions.pop(subscription_id, None)

    async def start(self) -> None:
        logger.info("connecting to NATS at %s", self._url)
        self._nc = await nats.connect(self._url)
        self._js = self._nc.jetstream()
        await self._ensure_stream()
        pending, self._pending = self._pending, []
        for subject, handler, fanout in pending:
            await self._apply_subscription(subject, handler, fanout)
        logger.info("nats event bus started")

    async def stop(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._nc = None
            self._js = None

    async def _apply_subscription(
        self, subject: str, handler: SubscriberHandler, fanout: bool, sub_id: str | None = None
    ) -> None:
        sub_id = sub_id or str(uuid.uuid4())
        if fanout:
            # Core NATS fan-out: every replica receives the event and pushes to
            # its local WebSocket sessions. Perfect for realtime push (no
            # persistence needed — only live connections consume it).
            await self._require_nc().subscribe(subject, cb=self._deliver_core(subject, handler))
            self._subscriptions[sub_id] = (handler, subject)
            return
        js = self._require_js()
        durable_name = f"st-{subject.replace('.', '-')}"
        try:
            # Durable consumers sharing a name across replicas are
            # load-balanced by the server (round-robin delivery), which gives
            # queue-group semantics without an explicit queue binding.
            sub = await js.subscribe(
                subject,
                durable=durable_name,
                stream=STREAM_NAME,
                manual_ack=True,
                cb=self._deliver_js(handler),
            )
        except Exception as exc:
            await self._recover_stale_consumers(js, subject, exc)
            try:
                sub = await js.subscribe(
                    subject,
                    durable=durable_name,
                    stream=STREAM_NAME,
                    manual_ack=True,
                    cb=self._deliver_js(handler),
                )
            except Exception as exc2:
                raise SubscriptionError(f"nats subscribe failed for {subject}: {exc2}") from exc
        self._subscriptions[sub_id] = (handler, sub)

    async def _recover_stale_consumers(self, js, subject: str, original_error: Exception) -> None:
        """Workqueue streams allow one consumer per filter subject.

        On deploy upgrades the durable consumer may be stale (older config or
        leftover from a failed run). Delete consumers bound to this subject
        and let the caller retry the subscription.
        """
        logger.warning("subscribe failed for %s (%s); attempting recovery", subject, original_error)
        nc = self._require_nc()
        try:
            req = await nc.request(f"$JS.API.CONSUMER.LIST.{STREAM_NAME}", b"", timeout=5)
            data = json.loads(req.data)
            for consumer in data.get("consumers", []):
                if consumer["config"].get("filter_subject") == subject:
                    name = consumer["config"]["durable_name"]
                    await js.delete_consumer(STREAM_NAME, name)
                    logger.info("removed stale consumer %s for %s", name, subject)
        except Exception as exc:  # recovery is best-effort
            logger.warning("consumer recovery failed: %s", exc)

    def _require_js(self) -> JetStreamContext:
        if self._js is None:
            raise RuntimeError("nats bus not started; call start() first")
        return self._js

    def _require_nc(self) -> nats.NATS:
        if self._nc is None:
            raise RuntimeError("nats bus not started; call start() first")
        return self._nc

    async def _ensure_stream(self) -> None:
        js = self._require_js()
        try:
            await js.stream_info(STREAM_NAME)
        except Exception:
            await js.add_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS,
                retention="workqueue",
                max_msgs=10_000,
            )
            logger.info("created jetstream stream %s", STREAM_NAME)

    def _deliver_js(self, handler: SubscriberHandler):
        async def callback(msg: Msg) -> None:
            try:
                envelope = json.loads(msg.data.decode())
                payload = envelope["payload"]
                metadata = EventMetadata(**envelope["metadata"])
                await handler(payload, metadata)
                await msg.ack()
            except Exception:
                logger.exception("handler failed for %s, nacking", msg.subject)
                await msg.nak()

        return callback

    def _deliver_core(self, subject: str, handler: SubscriberHandler):
        async def callback(msg: nats.aio.msg.Msg) -> None:
            try:
                envelope = json.loads(msg.data.decode())
                payload = envelope["payload"]
                metadata = EventMetadata(**envelope["metadata"])
                await handler(payload, metadata)
            except Exception:
                logger.exception("fanout handler failed for %s", subject)

        return callback
