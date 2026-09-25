"""Integration tests against a real NATS server with JetStream enabled.

These tests are skipped when no NATS server is reachable. Start one with:

    ./scripts/nats.sh start     # or: make nats-up

The NATS URL is resolved in this order:
1. $NATS_URL
2. settings.nats_url (defaults to nats://localhost:4222)
3. the Docker host derived from $DOCKER_HOST (remote docker daemons publish
   the container port on the daemon's host, not on localhost)
"""

from __future__ import annotations

import asyncio
import inspect
import os
import uuid

import nats
import pytest

from src.db.session import SessionFactory
from src.events.bus import SubscriptionError
from src.events.factory import WorkflowRegistry
from src.events.nats import STREAM_SUBJECTS, NatsEventBus
from src.events.subjects import Subjects
from src.realtime.manager import ConnectionManager
from src.services.auth import AuthService
from src.settings import settings
from src.workflows import build_workflows

STREAM_NAME = settings.nats_stream_name_effective
MAX_DELIVER = 10
ACK_WAIT_SECONDS = 30.0


def _docker_host_from_env() -> str | None:
    docker_host = os.environ.get("DOCKER_HOST", "")
    if docker_host.startswith("tcp://"):
        host = docker_host.split("//")[1].rsplit(":", 1)[0]
        return f"nats://{host}:4222"
    return None


def _url_candidates() -> list[str]:
    from src.settings import settings

    candidates = [os.environ.get("NATS_URL"), settings.nats_url, "nats://localhost:4222"]
    extra = _docker_host_from_env()
    if extra and extra not in candidates:
        candidates.append(extra)
    return [c for c in candidates if c]


async def _nats_reachable(url: str) -> bool:
    try:
        nc = await asyncio.wait_for(
            nats.connect(
                url,
                connect_timeout=1.0,
                allow_reconnect=False,
                max_reconnect_attempts=0,
            ),
            timeout=3,
        )
        await nc.close()
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
async def nats_url() -> str:
    for url in _url_candidates():
        if await _nats_reachable(url):
            return url
    pytest.skip(
        "NATS server not reachable; start one with `make nats-up` and set NATS_URL to point at it"
    )


@pytest.fixture
async def clean_stream(nats_url: str) -> None:
    """Wipe the stream and its consumers so tests see a clean slate."""
    nc = await nats.connect(nats_url, connect_timeout=2.0)
    js = nc.jetstream()
    try:
        await js.stream_info(STREAM_NAME)
    except Exception:
        await js.add_stream(name=STREAM_NAME, subjects=STREAM_SUBJECTS, retention="workqueue")
    consumers = await js.consumers_info(STREAM_NAME)
    for consumer in consumers:
        await js.delete_consumer(STREAM_NAME, consumer.name)
    await js.purge_stream(STREAM_NAME)
    await nc.close()


@pytest.fixture
async def bus(nats_url: str, clean_stream: None):
    instance = NatsEventBus(nats_url)
    await instance.start()
    yield instance
    await instance.stop()


def _unique_subject(prefix: str = "workspaces") -> str:
    return f"{prefix}.test-{uuid.uuid4().hex[:12]}"


async def _collect(
    instance: NatsEventBus, subject: str, *, fanout: bool = False, timeout_secs: float = 5.0
):
    received: list[tuple[dict, object]] = []

    async def handler(payload, metadata):
        received.append((payload, metadata))

    sub_id = await instance.subscribe(subject, handler, fanout=fanout)
    return received, sub_id


async def _wait_for(predicate, timeout_secs: float = 5.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_secs
    while loop.time() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------- basics


async def test_stream_created_with_expected_subjects(bus: NatsEventBus):
    js = bus._require_js()
    info = await js.stream_info(STREAM_NAME)
    assert set(info.config.subjects) == set(STREAM_SUBJECTS)
    assert info.config.retention == "workqueue"


async def test_durable_roundtrip(bus: NatsEventBus):
    subject = _unique_subject()
    received, _ = await _collect(bus, subject)
    await bus.publish(subject, {"value": 42}, correlation_id="corr-1")
    assert await _wait_for(lambda: len(received) == 1)
    payload, metadata = received[0]
    assert payload == {"value": 42}
    assert metadata.subject == subject
    assert metadata.correlation_id == "corr-1"


async def test_buffered_publish_before_start(nats_url: str, clean_stream: None):
    instance = NatsEventBus(nats_url)
    subject = _unique_subject()
    received, _ = await _collect(instance, subject)  # subscribe before start
    await instance.publish(subject, {"buffered": True})  # buffered before start
    assert received == []
    await instance.start()
    try:
        assert await _wait_for(lambda: len(received) == 1)
        assert received[0][0] == {"buffered": True}
    finally:
        await instance.stop()


async def test_durable_replay_from_persistence(bus: NatsEventBus):
    """A durable consumer created after a publish still receives the message."""
    subject = _unique_subject()
    await bus.publish(subject, {"persisted": True})
    received, _ = await _collect(bus, subject)
    assert await _wait_for(lambda: len(received) == 1)
    assert received[0][0] == {"persisted": True}


# ------------------------------------------------------------ transient


async def test_transient_publish_reaches_fanout_and_is_not_persisted(bus: NatsEventBus):
    js = bus._require_js()
    before = (await js.stream_info(STREAM_NAME)).state.messages

    subject = _unique_subject("notifications")
    received, _ = await _collect(bus, subject, fanout=True)
    await bus.publish(subject, {"realtime": True}, transient=True)
    assert await _wait_for(lambda: len(received) == 1)
    assert received[0][0] == {"realtime": True}

    after = (await js.stream_info(STREAM_NAME)).state.messages
    assert after == before  # transient publish never touched JetStream


async def test_durable_subscription_on_transient_subject_rejected(bus: NatsEventBus):
    with pytest.raises(SubscriptionError):
        await bus.subscribe(Subjects.NOTIFICATIONS_CREATED, lambda p, m: None)


async def test_fanout_core_subscription_receives_durable_publish(bus: NatsEventBus):
    subject = _unique_subject()
    fanout_received, _ = await _collect(bus, subject, fanout=True)
    await bus.publish(subject, {"both": True})
    assert await _wait_for(lambda: len(fanout_received) == 1)


# --------------------------------------------------------------- lifecycle


async def test_unsubscribe_stops_delivery(bus: NatsEventBus):
    subject = _unique_subject()
    received, sub_id = await _collect(bus, subject)
    await bus.publish(subject, {"one": 1})
    assert await _wait_for(lambda: len(received) == 1)
    await bus.unsubscribe(sub_id)
    await bus.publish(subject, {"two": 2})
    await asyncio.sleep(0.3)
    assert len(received) == 1


async def test_durable_consumer_config(bus: NatsEventBus):
    subject = _unique_subject()
    durable_name = f"st-{subject.replace('.', '-')}"
    received, sub_id = await _collect(bus, subject)
    await bus.publish(subject, {"cfg": True})
    assert await _wait_for(lambda: len(received) == 1)
    await bus.unsubscribe(sub_id)

    js = bus._require_js()
    consumers = await js.consumers_info(STREAM_NAME)
    consumer = next(c for c in consumers if c.name == durable_name)
    assert consumer.config.max_deliver == MAX_DELIVER
    assert consumer.config.ack_wait == ACK_WAIT_SECONDS
    assert consumer.config.max_ack_pending == 500
    assert consumer.config.filter_subject == subject


# ------------------------------------------------------- end-to-end


async def test_workflow_end_to_end_over_nats(nats_url: str, clean_stream: None):
    """Publish member.invited + audit events over real NATS and verify the
    workflows persist rows and fan out notifications via the transient bus."""
    from sqlalchemy import func, select

    from src.models.audit import AuditLogEntry
    from src.models.core import Notification

    async with SessionFactory() as session:
        user = await AuthService(session).register(
            email="nats-e2e@example.com",
            password="Password123!",
            first_name="NATS",
            last_name="E2E",
        )

    bus_instance = NatsEventBus(nats_url)
    registry = WorkflowRegistry(bus_instance)
    build_workflows(registry, bus_instance, ConnectionManager())
    await registry.wire()
    await registry.start()
    try:
        await bus_instance.publish(
            Subjects.WORKSPACE_MEMBER_INVITED,
            {
                "user_id": user.id,
                "workspace_id": "00000000-0000-0000-0000-000000000001",
                "workspace_name": "NATS Workspace",
                "invitation_id": "00000000-0000-0000-0000-000000000002",
                "invited_by": "Owner",
            },
        )
        await bus_instance.publish(
            Subjects.AUDIT_ENTRY_CREATED,
            {
                "workspace_id": "00000000-0000-0000-0000-000000000001",
                "actor_user_id": user.id,
                "resource_type": "user",
                "resource_id": user.id,
                "action": "user.login",
                "details": {"email": "nats-e2e@example.com"},
                "ip_address": "10.0.0.1",
            },
        )

        async def _notification_persisted() -> bool:
            async with SessionFactory() as session:
                result = await session.execute(
                    select(func.count())
                    .select_from(Notification)
                    .where(Notification.user_id == user.id)
                )
                return result.scalar_one() >= 1

        async def _audit_persisted() -> bool:
            async with SessionFactory() as session:
                result = await session.execute(
                    select(func.count())
                    .select_from(AuditLogEntry)
                    .where(AuditLogEntry.action == "user.login")
                )
                return result.scalar_one() >= 1

        assert await _wait_for(_notification_persisted, timeout_secs=10)
        assert await _wait_for(_audit_persisted, timeout_secs=10)

        async with SessionFactory() as session:
            result = await session.execute(
                select(Notification).where(Notification.user_id == user.id)
            )
            notification = result.scalars().first()
        assert notification.type == "workspace_invitation"
        assert notification.payload["workspace_name"] == "NATS Workspace"
    finally:
        await registry.stop()
