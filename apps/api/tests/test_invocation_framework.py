import tempfile
from pathlib import Path

import pytest

from src.agents.runners.local import LocalTmpRunner
from src.agents.runners.base import RunSpec
from src.agents.sessions.store import SessionStore
from src.events.subjects import ALL, TRANSIENT_SUBJECTS, Subjects


def test_subjects_registered():
    assert Subjects.AGENTS_REQUEST_CHAT in ALL
    assert Subjects.AGENTS_RUN_EVENT in ALL
    assert Subjects.AGENTS_PERMISSION_EVENT in ALL
    assert Subjects.AGENTS_RUN_EVENT in TRANSIENT_SUBJECTS
    assert Subjects.AGENTS_PERMISSION_EVENT in TRANSIENT_SUBJECTS
    assert Subjects.AGENTS_REQUEST_CHAT not in TRANSIENT_SUBJECTS  # durable queue


@pytest.mark.anyio
async def test_session_store_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        store = SessionStore(root=tmp)
        history = [{"type": "token", "data": {"text": "hi"}}, {"type": "done", "data": {}}]
        await store.write("ws1", "ag1", "conv1", "sess1", history)
        loaded = await store.read("ws1", "ag1", "conv1", "sess1")
        assert loaded == history
        assert await store.read("ws1", "ag1", "conv1", "missing") is None
        await store.delete("ws1", "ag1", "conv1", "sess1")
        assert await store.read("ws1", "ag1", "conv1", "sess1") is None


@pytest.mark.anyio
async def test_local_runner_provision_and_close():
    with tempfile.TemporaryDirectory() as tmp:
        runner = LocalTmpRunner()
        from src import settings as settings_mod

        orig = settings_mod.settings.agent_runner_root
        settings_mod.settings.agent_runner_root = tmp
        try:
            spec = RunSpec(workspace_id="ws", agent_id="ag", conversation_id="conv")
            handle = await runner.provision(spec)
            assert Path(handle.workdir).exists()
            events = [e async for e in runner.execute(handle, {"prompt": "hi"})]
            assert len(events) == 1 and events[0].type == "done"
            await runner.close(handle)
            assert not Path(handle.workdir).exists()
        finally:
            settings_mod.settings.agent_runner_root = orig


@pytest.mark.anyio
async def test_router_publishes_per_active_agent(app_client):
    from tests.conftest import auth_headers, create_workspace, register_user, ws_headers
    from src.db.session import SessionFactory
    from src.models.conversation import Conversation, ConversationParticipant
    from src.models.workspace import User
    from src.services.conversations import ConversationService

    client = app_client
    owner_tokens = await register_user(client, "router-owner@example.com")
    ws = await create_workspace(client, owner_tokens)
    hdr = ws_headers(owner_tokens, ws["id"])

    me = await client.get("/api/v1/auth/me", headers=auth_headers(owner_tokens))
    owner_id = me.json()["id"]

    r = await client.post("/api/v1/agents", json={"name": "Bot A", "slug": "bot-a"}, headers=hdr)
    assert r.status_code == 201
    bot_a = r.json()["id"]
    r = await client.post("/api/v1/agents", json={"name": "Bot B", "slug": "bot-b"}, headers=hdr)
    assert r.status_code == 201
    bot_b = r.json()["id"]
    r = await client.post("/api/v1/agents", json={"name": "Sleepy", "slug": "sleepy", "is_active": False}, headers=hdr)
    assert r.status_code == 201
    sleepy = r.json()["id"]

    async with SessionFactory() as session:
        conv = Conversation(workspace_id=ws["id"], created_by_user_id=owner_id, title="Test")
        session.add(conv)
        await session.flush()
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        session.add(
            ConversationParticipant(
                conversation_id=conv.id,
                participant_type="user",
                participant_id=owner_id,
                user_id=owner_id,
                joined_at=now,
            )
        )
        for aid in [bot_a, bot_b, sleepy]:
            session.add(
                ConversationParticipant(
                    conversation_id=conv.id,
                    participant_type="agent",
                    participant_id=aid,
                    agent_id=aid,
                    joined_at=now,
                )
            )
        await session.commit()
        conv_id = conv.id

    from src.main import app

    bus = app.state.container.bus
    collected: list[dict] = []

    async def collector(payload, metadata):
        collected.append(payload)

    sub_id = await bus.subscribe(Subjects.AGENTS_REQUEST_CHAT, collector)

    async with SessionFactory() as session:
        user_row = await session.get(User, owner_id)
        svc = ConversationService(session, bus)
        await svc.send_message(workspace_id=ws["id"], conversation_id=conv_id, sender=user_row, body="hello agents")

    import asyncio

    await asyncio.sleep(0.5)
    await bus.unsubscribe(sub_id)

    agent_ids = {p["agent_id"] for p in collected}
    assert bot_a in agent_ids
    assert bot_b in agent_ids
    assert sleepy not in agent_ids
    assert len(collected) == 2
