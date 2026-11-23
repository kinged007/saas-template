from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import asdict

import nats
from nats.aio.msg import Msg
from nats.js import JetStreamContext
from nats.js.api import ConsumerConfig

from src.events.bus import (
    EventBus,
    EventEnvelope,
    EventMetadata,
    PublishError,
    SubscriberHandler,
    SubscriptionError,
)
from src.events.subjects import TRANSIENT_SUBJECTS, Subjects

logger = logging.getLogger(__name__)

STREAM_NAME = "SAAS_TEMPLATE"
STREAM_SUBJECTS = [
    f"{Subjects.WORKSPACES}.>",
    f"{Subjects.APIKEYS}.>",
    f"{Subjects.AUDIT}.>",
    f"{Subjects.JOBS}.>",
    f"{Subjects.CONVERSATIONS}.>",
]
MAX_DELIVER = 10
ACK_WAIT_SECONDS = 30.0


class NatsEventBus(EventBus):
    """Production event bus backed by NATS JetStream.

    - One stream (SAAS_TEMPLATE, workqueue retention) with subjects for each
      durable namespace (workspaces.>, apikeys.>, audit.>, jobs.>,
      conversations.>).
    - Each durable subscription is a durable consumer: events survive
      restarts, are delivered with acks, and load-balance across replicas
      (shared durable name = queue-group semantics). Messages are acked after
      the handler completes, nacked on failure (bounded by MAX_DELIVER).
    - Fanout subscriptions (`fanout=True`) use core NATS: every replica
      receives the event, which is what realtime WebSocket push needs.
    - Transient publishes (see Subjects.TRANSIENT_SUBJECTS) go over core
      NATS without persistence; durable subscriptions on transient subjects
      are rejected so a silent "consumer never receives anything" cannot
      happen.
    - Publishes issued before start() are buffered and flushed after the
      stream and subscriptions are ready (same buffering contract as the
      in-process bus).
    """

    name = "nats"

    def __init__(self, url: str, *, queue_group: str = "saas-template-workers") -> None:
        self._url = url
        self._queue_group = queue_group
        self._nc: nats.NATS | None = None
        self._js: JetStreamContext | None = None
        self._subscriptions: dict[str, tuple[SubscriberHandler, object]] = {}
        self._pending_subs: list[tuple[str, SubscriberHandler, bool]] = []
        self._pending_publishes: list[tuple[str, dict, str | None, bool]] = []
        self._tasks: list[asyncio.Task] = []

    async def publish(
        self,
        subject: str,
        payload: dict,
        *,
        correlation_id: str | None = None,
        transient: bool = False,
    ) -> None:
        if self._nc is None:
            # Not connected yet (startup window): buffer, like the in-process
            # bus buffers until its consumer tasks are running.
            self._pending_publishes.append((subject, payload, correlation_id, transient))
            return
        metadata = EventMetadata(
            subject=subject,
            correlation_id=correlation_id or "",
        )
        envelope = EventEnvelope(metadata=metadata, payload=payload)
        data = json.dumps(asdict(envelope)).encode()
        try:
            if transient or subject in TRANSIENT_SUBJECTS:
                await self._require_nc().publish(subject, data)
            else:
                await self._require_js().publish(subject, data)
        except Exception as exc:
            raise PublishError(f"nats publish failed for {subject}: {exc}") from exc

    async def subscribe(
        self, subject: str, handler: SubscriberHandler, *, fanout: bool = False
    ) -> str:
        sub_id = str(uuid.uuid4())
        if self._nc is None:
            # Not connected yet (workflows are wired before start()): defer.
            self._pending_subs.append((subject, handler, fanout))
            return sub_id
        await self._apply_subscription(subject, handler, fanout, sub_id)
        return sub_id

    async def unsubscribe(self, subscription_id: str) -> None:
        entry = self._subscriptions.pop(subscription_id, None)
        if entry is None:
            return
        _, sub = entry
        try:
            await sub.unsubscribe()
        except Exception as exc:
            logger.warning("unsubscribe failed for %s: %s", subscription_id, exc)

    async def start(self) -> None:
        if self._nc is not None:
            return
        logger.info("connecting to NATS at %s", self._url)
        self._nc = await nats.connect(self._url)
        self._js = self._nc.jetstream()
        await self._ensure_stream()
        pending_subs, self._pending_subs = self._pending_subs, []
        for subject, handler, fanout in pending_subs:
            await self._apply_subscription(subject, handler, fanout)
        pending_publishes, self._pending_publishes = self._pending_publishes, []
        for subject, payload, correlation_id, transient in pending_publishes:
            await self.publish(subject, payload, correlation_id=correlation_id, transient=transient)
        logger.info("nats event bus started (%d subscriptions)", len(self._subscriptions))

    async def stop(self) -> None:
        if self._nc:
            await self._nc.drain()
            self._nc = None
            self._js = None
        if self._pending_publishes:
            logger.warning("dropping %d buffered publishes at stop", len(self._pending_publishes))
            self._pending_publishes.clear()

    async def wait_idle(self) -> None:
        """No-op: delivery happens server-side, so there is nothing local to
        drain. Tests running against NATS must keep polling the database."""

    async def _apply_subscription(
        self, subject: str, handler: SubscriberHandler, fanout: bool, sub_id: str | None = None
    ) -> None:
        sub_id = sub_id or str(uuid.uuid4())
        if fanout:
            # Core NATS fan-out: every replica receives the event and pushes to
            # its local WebSocket sessions. Perfect for realtime push (no
            # persistence needed — only live connections consume it).
            sub = await self._require_nc().subscribe(
                subject, cb=self._deliver_core(subject, handler)
            )
            self._subscriptions[sub_id] = (handler, sub)
            return
        if subject in TRANSIENT_SUBJECTS:
            raise SubscriptionError(
                f"durable subscription on transient subject {subject} would never receive "
                "messages; subscribe with fanout=True or move the subject to the durable set"
            )
        js = self._require_js()
        durable_name = f"st-{subject.replace('.', '-')}"
        try:
            sub = await js.subscribe(
                subject,
                durable=durable_name,
                stream=STREAM_NAME,
                manual_ack=True,
                config=ConsumerConfig(
                    ack_wait=ACK_WAIT_SECONDS,
                    max_deliver=MAX_DELIVER,
                    max_ack_pending=500,
                ),
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
                    config=ConsumerConfig(
                        ack_wait=ACK_WAIT_SECONDS,
                        max_deliver=MAX_DELIVER,
                        max_ack_pending=500,
                    ),
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
            info = await js.stream_info(STREAM_NAME)
        except Exception:
            await js.add_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS,
                retention="workqueue",
                max_msgs=10_000,
            )
            logger.info("created jetstream stream %s", STREAM_NAME)
            return
        if set(info.config.subjects) != set(STREAM_SUBJECTS):
            await js.update_stream(
                name=STREAM_NAME,
                subjects=STREAM_SUBJECTS,
                retention="workqueue",
                max_msgs=10_000,
            )
            logger.info("reconciled stream %s subjects", STREAM_NAME)

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
