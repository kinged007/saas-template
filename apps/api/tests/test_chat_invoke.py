import asyncio

import pytest
from sqlalchemy import select

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


@pytest.mark.anyio
async def test_chat_with_agent_replies_and_session_history(app_client):
    client = app_client
    owner = await register_user(client, "chat-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    # create active agent
    r = await client.post("/api/v1/agents", json={"name": "Helper", "slug": "helper"}, headers=hdr)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    # need a second human member to satisfy "at least one other participant" (we include self + other via participant_user_ids)
    # create second user and add to workspace
    other = await register_user(client, "other@example.com")
    # invite other as viewer/editor
    roles = await client.get("/api/v1/roles", headers=hdr)
    role_id = next(x["id"] for x in roles.json() if x["name"] == "viewer")
    inv = await client.post("/api/v1/invitations", json={"email": "other@example.com", "role_id": role_id}, headers=hdr)
    assert inv.status_code == 201, inv.text
    token = inv.json()["token"]
    acc = await client.post("/api/v1/invitations/accept", params={"token": token}, headers=auth_headers(other))
    assert acc.status_code == 200, acc.text
    other_me = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    other_id = other_me.json()["id"]

    # create conversation including agent
    r = await client.post(
        "/api/v1/conversations",
        json={
            "participant_user_ids": [other_id],
            "participant_agent_ids": [agent_id],
            "initial_message": "hello agents",
        },
        headers=hdr,
    )
    assert r.status_code == 201, r.text
    conv = r.json()
    conv_id = conv["id"]
    # participants should include agent
    assert any(p["type"] == "agent" and p["id"] == agent_id for p in conv["participants"])

    # initial messages: 1
    r = await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)
    assert r.status_code == 200, r.text
    assert len(r.json()) == 1
    assert r.headers.get("X-Total-Count") == "1"

    # send second user message, should trigger agent reply
    r = await client.post(f"/api/v1/conversations/{conv_id}/messages", json={"body": "ping"}, headers=hdr)
    assert r.status_code == 201, r.text

    # wait for async handler to persist reply
    for _ in range(20):
        await asyncio.sleep(0.25)
        r = await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)
        msgs = r.json()
        if len(msgs) >= 3 and any(m["sender_type"] == "agent" for m in msgs):
            break
    else:
        pytest.fail(f"agent reply did not appear: {msgs}")

    # session history should have at least one step (collapsed enrichment)
    r = await client.get(f"/api/v1/conversations/{conv_id}/session-history", headers=hdr)
    assert r.status_code == 200, r.text
    steps = r.json()
    assert isinstance(steps, list) and len(steps) >= 1
    assert any("content" in s for s in steps)


@pytest.mark.anyio
async def test_chat_loop_prevention(app_client):
    """Agent message itself must not re-trigger another agent request."""
    client = app_client
    owner = await register_user(client, "loop-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])
    r = await client.post("/api/v1/agents", json={"name": "Looper", "slug": "looper"}, headers=hdr)
    agent_id = r.json()["id"]
    other = await register_user(client, "loop-other@example.com")
    roles = await client.get("/api/v1/roles", headers=hdr)
    role_id = next(x["id"] for x in roles.json() if x["name"] == "viewer")
    inv = await client.post("/api/v1/invitations", json={"email": "loop-other@example.com", "role_id": role_id}, headers=hdr)
    token = inv.json()["token"]
    await client.post("/api/v1/invitations/accept", params={"token": token}, headers=auth_headers(other))
    other_me = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    other_id = other_me.json()["id"]

    r = await client.post(
        "/api/v1/conversations",
        json={"participant_user_ids": [other_id], "participant_agent_ids": [agent_id], "initial_message": "hi"},
        headers=hdr,
    )
    conv_id = r.json()["id"]
    # wait initial reply
    await asyncio.sleep(0.8)
    r = await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)
    before = len(r.json())
    # wait a bit more — should not keep growing (loop would double)
    await asyncio.sleep(0.8)
    r = await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)
    after = len(r.json())
    # at most one more than before (if initial reply just landed), not infinite loop
    assert after <= before + 1, f"loop detected: before {before} after {after}"


@pytest.mark.anyio
async def test_chat_inactive_agent_no_reply(app_client):
    client = app_client
    owner = await register_user(client, "inactive-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])
    r = await client.post("/api/v1/agents", json={"name": "Sleepy", "slug": "sleepy", "is_active": False}, headers=hdr)
    agent_id = r.json()["id"]
    other = await register_user(client, "inactive-other@example.com")
    roles = await client.get("/api/v1/roles", headers=hdr)
    role_id = next(x["id"] for x in roles.json() if x["name"] == "viewer")
    inv = await client.post("/api/v1/invitations", json={"email": "inactive-other@example.com", "role_id": role_id}, headers=hdr)
    token = inv.json()["token"]
    await client.post("/api/v1/invitations/accept", params={"token": token}, headers=auth_headers(other))
    other_me = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    other_id = other_me.json()["id"]

    # inactive agent should be rejected on create_conversation
    r = await client.post(
        "/api/v1/conversations",
        json={"participant_user_ids": [other_id], "participant_agent_ids": [agent_id], "initial_message": "hi"},
        headers=hdr,
    )
    assert r.status_code == 400
    assert "inactive" in r.text.lower()


@pytest.mark.anyio
async def test_chat_cross_workspace_agent_rejected(app_client):
    client = app_client
    owner = await register_user(client, "cross-owner@example.com")
    ws1 = await create_workspace(client, owner, name="W1")
    ws2 = await create_workspace(client, owner, name="W2")
    h1 = ws_headers(owner, ws1["id"])
    h2 = ws_headers(owner, ws2["id"])
    r = await client.post("/api/v1/agents", json={"name": "W2Bot", "slug": "w2bot"}, headers=h2)
    agent_id = r.json()["id"]
    other = await register_user(client, "cross-other@example.com")
    roles = await client.get("/api/v1/roles", headers=h1)
    role_id = next(x["id"] for x in roles.json() if x["name"] == "viewer")
    inv = await client.post("/api/v1/invitations", json={"email": "cross-other@example.com", "role_id": role_id}, headers=h1)
    token = inv.json()["token"]
    await client.post("/api/v1/invitations/accept", params={"token": token}, headers=auth_headers(other))
    other_me = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    other_id = other_me.json()["id"]

    r = await client.post(
        "/api/v1/conversations",
        json={"participant_user_ids": [other_id], "participant_agent_ids": [agent_id], "initial_message": "hi"},
        headers=h1,
    )
    assert r.status_code == 400


@pytest.mark.anyio
async def test_agent_only_conversation(app_client):
    """A conversation with no humans — just one or more agents — is valid."""
    client = app_client
    owner = await register_user(client, "agent-only-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])
    r = await client.post("/api/v1/agents", json={"name": "Solo", "slug": "solo"}, headers=hdr)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    r = await client.post(
        "/api/v1/conversations",
        json={"participant_user_ids": [], "participant_agent_ids": [agent_id], "initial_message": "hello"},
        headers=hdr,
    )
    assert r.status_code == 201, r.text
    conv = r.json()
    assert any(p["type"] == "agent" and p["id"] == agent_id for p in conv["participants"])
    # creator is still a participant
    assert any(p["type"] == "user" for p in conv["participants"])

    # no participants at all → 422 (schema-level validator)
    r = await client.post(
        "/api/v1/conversations",
        json={"participant_user_ids": [], "initial_message": "hi"},
        headers=hdr,
    )
    assert r.status_code == 422

    # agent-only conversation flows through the pipeline: wait for agent reply
    conv_id = conv["id"]
    for _ in range(20):
        await asyncio.sleep(0.25)
        msgs = (await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)).json()
        if any(m["sender_type"] == "agent" for m in msgs):
            break
    assert any(m["sender_type"] == "agent" for m in msgs), f"no agent reply in {msgs}"
