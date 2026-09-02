import uuid

import pytest

from src.agents.handlers.base import AgentContext, AgentEvent, AgentRequest
from src.agents.handlers.chat import ChatHandler
from src.agents.memory import MemoryStore
from src.db.session import SessionFactory
from src.models.agent import Agent
from src.models.conversation import Conversation, Message


async def _seed_agent_and_conversation(
    workspace_id: str, agent_id: str, conversation_id: str
) -> None:
    async with SessionFactory() as session:
        session.add(
            Agent(
                id=agent_id,
                workspace_id=workspace_id,
                slug="mem",
                name="MemoryAgent",
                is_active=True,
            )
        )
        session.add(
            Conversation(
                id=conversation_id,
                workspace_id=workspace_id,
                created_by_user_id=str(uuid.uuid4()),
            )
        )
        await session.commit()


@pytest.mark.anyio
async def test_memory_persists_and_is_retrieved_for_same_triple(app_client):
    """A memory written in one turn is retrievable in a later turn of the same triple."""
    store = MemoryStore()
    ws, agent, user = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    added = await store.upsert_many(
        ws,
        agent,
        user,
        None,
        [
            {"kind": "fact", "content": "user prefers embedded postgres over docker"},
            {"kind": "preference", "content": "reply in short bullet points"},
        ],
    )
    assert added == 2

    got = await store.retrieve(ws, agent, user)
    assert {m["content"] for m in got} == {
        "user prefers embedded postgres over docker",
        "reply in short bullet points",
    }
    assert {m["kind"] for m in got} == {"fact", "preference"}

    # upsert of identical content dedupes instead of duplicating
    added_again = await store.upsert_many(
        ws,
        agent,
        user,
        None,
        [{"kind": "fact", "content": "user prefers embedded postgres over docker"}],
    )
    assert added_again == 0
    assert len(await store.retrieve(ws, agent, user)) == 2


@pytest.mark.anyio
async def test_memory_isolation_between_users(app_client):
    """Required isolation: user A's memories are empty for user B on the same agent + workspace."""
    store = MemoryStore()
    ws, agent = str(uuid.uuid4()), str(uuid.uuid4())
    user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())

    await store.upsert_many(
        ws, agent, user_a, None, [{"kind": "fact", "content": "a-private-taste"}]
    )

    assert await store.retrieve(ws, agent, user_b) == []
    # same user + workspace, different agent: also isolated
    other_agent = str(uuid.uuid4())
    assert await store.retrieve(ws, other_agent, user_a) == []


@pytest.mark.anyio
async def test_memory_cross_workspace_denied(app_client):
    store = MemoryStore()
    ws_a, ws_b = str(uuid.uuid4()), str(uuid.uuid4())
    agent, user = str(uuid.uuid4()), str(uuid.uuid4())

    await store.upsert_many(ws_a, agent, user, None, [{"kind": "fact", "content": "ws-a-secret"}])
    assert await store.retrieve(ws_b, agent, user) == []


@pytest.mark.anyio
async def test_memory_upsert_rejects_unknown_kinds(app_client):
    """Barricade: unvalidated kinds never reach the table."""
    store = MemoryStore()
    ws, agent, user = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    added = await store.upsert_many(
        ws,
        agent,
        user,
        None,
        [
            {"kind": "rumor", "content": "not a real kind"},
            {"kind": "", "content": "empty kind"},
            {"kind": "fact", "content": ""},  # empty content
        ],
    )
    assert added == 0
    assert await store.retrieve(ws, agent, user) == []


@pytest.mark.anyio
async def test_memory_prune_caps_per_kind(app_client, monkeypatch):
    from src.settings import settings

    monkeypatch.setattr(settings, "agent_memory_prune_keep", 2)
    store = MemoryStore()
    ws, agent, user = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())

    await store.upsert_many(
        ws,
        agent,
        user,
        None,
        [
            {"kind": "fact", "content": f"fact {i}"} for i in range(4)
        ]
        + [{"kind": "preference", "content": f"pref {i}"} for i in range(3)],
    )
    deleted = await store.prune(ws, agent, user)
    assert deleted == 3  # 2 facts + 1 preference beyond the cap

    got = await store.retrieve(ws, agent, user)
    assert sum(1 for m in got if m["kind"] == "fact") == 2
    assert sum(1 for m in got if m["kind"] == "preference") == 2


@pytest.mark.anyio
async def test_chat_turn_extracts_memories_and_next_turn_retrieves_them(app_client, monkeypatch):
    """End-to-end: post_process extracts+stores; collect_context injects the
    same user's memories into the next turn and never another user's."""
    from src.agents import llm as llm_mod

    ws, agent_id, conv_id = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    user_a, user_b = str(uuid.uuid4()), str(uuid.uuid4())
    await _seed_agent_and_conversation(ws, agent_id, conv_id)

    async def fake_extract(*, model, env, transcript, http=None):
        assert "dark mode" in transcript
        return [
            {"kind": "fact", "content": "user loves dark mode"},
            {"kind": "preference", "content": "keep replies under 40 words"},
        ]

    monkeypatch.setattr(llm_mod, "extract_memories", fake_extract)

    handler = ChatHandler(bus=None, secret_store=None)
    message_id = str(uuid.uuid4())
    async with SessionFactory() as session:
        session.add(
            Message(
                id=message_id,
                conversation_id=conv_id,
                sender_type="user",
                sender_id=user_a,
                sender_user_id=user_a,
                body="I love dark mode",
            )
        )
        await session.commit()
    req = AgentRequest(
        entity_type="chat",
        conversation_id=conv_id,
        message_id=message_id,
        agent_id=agent_id,
        workspace_id=ws,
        triggering_user_id=user_a,
    )
    ctx = AgentContext(request=req)
    events = [AgentEvent(type="token", data={"text": "Sure thing!"})]
    await handler.post_process(req, ctx, events, None)

    # memories persisted under user_a's triple
    store = MemoryStore()
    got = await store.retrieve(ws, agent_id, user_a)
    assert {m["content"] for m in got} == {"user loves dark mode", "keep replies under 40 words"}

    # next turn of the SAME user retrieves them
    ctx_a = await handler.collect_context(req)
    expected_memories = {"user loves dark mode", "keep replies under 40 words"}
    assert {m["content"] for m in ctx_a.memories} == expected_memories

    # a different user's turn sees nothing (isolation through the handler)
    req_b = AgentRequest(
        entity_type="chat",
        conversation_id=conv_id,
        message_id=str(uuid.uuid4()),
        agent_id=agent_id,
        workspace_id=ws,
        triggering_user_id=user_b,
    )
    ctx_b = await handler.collect_context(req_b)
    assert ctx_b.memories == []