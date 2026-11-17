import asyncio

from src.events.bus import subject_matches
from src.events.inprocess import InProcessEventBus


def test_subject_wildcards():
    assert subject_matches("notifications.*", "notifications.created")
    assert subject_matches("workspaces.>", "workspaces.member.invited")
    assert not subject_matches("notifications", "notifications.created")
    assert not subject_matches("workspaces.*", "other.created")


async def test_inprocess_pubsub():
    bus = InProcessEventBus()
    received = []

    async def handler(payload, metadata):
        received.append((payload, metadata))

    await bus.subscribe("workspaces.member.invited", handler)
    await bus.start()
    await bus.publish("workspaces.member.invited", {"user_id": "u1"})
    await asyncio.sleep(0.05)
    await bus.stop()

    assert len(received) == 1
    assert received[0][0] == {"user_id": "u1"}
    assert received[0][1].subject == "workspaces.member.invited"


async def test_inprocess_wildcard_subscription():
    bus = InProcessEventBus()
    received = []

    async def handler(payload, metadata):
        received.append(payload)

    await bus.subscribe("notifications.>", handler)
    await bus.start()
    await bus.publish("notifications.created", {"id": "n1"})
    await bus.publish("notifications.updated", {"id": "n1"})
    await bus.publish("other", {"id": "x"})
    await asyncio.sleep(0.05)
    await bus.stop()

    assert len(received) == 2


async def test_inprocess_buffers_publishes_until_start():
    bus = InProcessEventBus()
    received = []

    async def handler(payload, metadata):
        received.append(payload)

    await bus.subscribe("workspaces.created", handler)
    # Published before start: must be buffered and delivered after start.
    await bus.publish("workspaces.created", {"workspace_id": "w1"})
    assert received == []
    await bus.start()
    await asyncio.sleep(0.05)
    await bus.stop()
    assert received == [{"workspace_id": "w1"}]


async def test_inprocess_publish_after_stop_is_dropped():
    bus = InProcessEventBus()
    received = []

    async def handler(payload, metadata):
        received.append(payload)

    await bus.subscribe("workspaces.created", handler)
    await bus.start()
    await asyncio.sleep(0.01)
    await bus.stop()
    await bus.publish("workspaces.created", {"workspace_id": "w2"})
    await asyncio.sleep(0.05)
    assert received == []


async def test_inprocess_unsubscribe_stops_delivery():
    bus = InProcessEventBus()
    received = []

    async def handler(payload, metadata):
        received.append(payload)

    sub_id = await bus.subscribe("workspaces.created", handler)
    await bus.start()
    await bus.publish("workspaces.created", {"workspace_id": "w1"})
    await asyncio.sleep(0.05)
    assert len(received) == 1
    await bus.unsubscribe(sub_id)
    await bus.publish("workspaces.created", {"workspace_id": "w2"})
    await asyncio.sleep(0.05)
    assert len(received) == 1
    await bus.stop()


async def test_inprocess_resubscribe_replaces_handler():
    bus = InProcessEventBus()
    first = []
    second = []

    async def handler_a(payload, metadata):
        first.append(payload)

    async def handler_b(payload, metadata):
        second.append(payload)

    await bus.subscribe("workspaces.created", handler_a)
    await bus.start()
    await bus.publish("workspaces.created", {"workspace_id": "w1"})
    await asyncio.sleep(0.05)
    assert len(first) == 1

    # Re-subscribing the same subject replaces the handler (and its task).
    await bus.subscribe("workspaces.created", handler_b)
    await bus.publish("workspaces.created", {"workspace_id": "w2"})
    await asyncio.sleep(0.05)
    assert len(first) == 1  # stale handler task cancelled, no duplicate delivery
    assert second == [{"workspace_id": "w2"}]
    await bus.stop()


async def test_inprocess_transient_and_durable_are_equivalent():
    bus = InProcessEventBus()
    received = []

    async def handler(payload, metadata):
        received.append(payload)

    await bus.subscribe("notifications.created", handler, fanout=True)
    await bus.start()
    await bus.publish("notifications.created", {"id": "n1"}, transient=True)
    await bus.publish("workspaces.created", {"id": "w1"})
    await asyncio.sleep(0.05)
    await bus.stop()
    assert len(received) == 1


async def test_workflow_registry_wiring(app_client):
    from src.container import Container
    from src.events.factory import WorkflowRegistry
    from src.workflows import build_workflows

    container = Container()
    registry = WorkflowRegistry(container.bus)
    build_workflows(registry, container.bus, container.connection_manager)
    assert set(registry.subjects) == {
        "workspaces.member.invited",
        "workspaces.member.joined",
        "workspaces.member.role_changed",
        "workspaces.member.removed",
        "workspaces.invitation.created",
        "workspaces.created",
        "audit.entry.created",
        "apikeys.created",
        "apikeys.revoked",
        "apikeys.updated",
        "jobs.execute",
        "notifications.created",
        "conversations.message.created",
        "conversations.message.live",
        "conversations.renamed",
    }
    await registry.wire()
    await registry.start()
    await registry.stop()
