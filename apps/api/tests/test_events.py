import asyncio

from src.events.inprocess import InProcessEventBus, _subject_matches


def test_subject_wildcards():
    assert _subject_matches("notifications.*", "notifications.created")
    assert _subject_matches("workspaces.>", "workspaces.member.invited")
    assert not _subject_matches("notifications", "notifications.created")
    assert not _subject_matches("workspaces.*", "other.created")


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


async def test_workflow_registry_wiring(app_client):
    from src.container import Container
    from src.events.factory import WorkflowRegistry
    from src.workflows import build_workflows

    container = Container()
    registry = WorkflowRegistry(container.bus)
    build_workflows(registry, container.bus, container.connection_manager)
    assert set(registry.subjects) == {
        "workspaces.member.invited",
        "notifications.created",
    }
    await registry.wire()
    await registry.start()
    await registry.stop()
