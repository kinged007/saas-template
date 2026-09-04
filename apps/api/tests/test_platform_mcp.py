import asyncio
import uuid

import pytest
from sqlalchemy import select

from src.db.session import SessionFactory
from src.mcp.platform.registry import get_registry, build_tools
from src.agents.handlers.chat import AgentDeps


def _deps(agent_perms, user_perms):
    return AgentDeps(workspace_id="ws", agent_id="ag", triggering_user_id="u", agent_perms=set(agent_perms), user_perms=set(user_perms))


@pytest.mark.anyio
async def test_registry_scope_deny_mutating_viewer_and_null_role(app_client):
    from pydantic_ai import Agent
    from pydantic_ai.models.test import TestModel
    from pydantic_ai.tools import DeferredToolRequests
    from src.mcp.platform.registry import _effective_perms  # type: ignore

    # viewer has only workspace:read → workspace.update (mutating, requires workspace:update) must be denied via effective perms
    assert "workspace:update" not in _effective_perms({"workspace:read"}, {"workspace:read"})
    # null role → deny all (empty agent perms) even if user has perms
    assert _effective_perms(set(), {"workspace:read"}) == set()
    # intersection: agent has update but user doesn't → denied
    eff = _effective_perms({"workspace:read", "workspace:update"}, {"workspace:read"})
    assert "workspace:update" not in eff


@pytest.mark.anyio
async def test_permission_request_pause_and_decision(app_client):
    # Create workspace + agent with owner role so gate can be exercised via HTTP
    from tests.conftest import auth_headers, create_workspace, register_user, ws_headers

    owner = await register_user(app_client, "pmcp-owner@example.com")
    ws = await create_workspace(app_client, owner)
    hdr = ws_headers(owner, ws["id"])
    # create agent with default role (owner) — has workspace:update so mutating tool allowed, hence deferred
    r = await app_client.post("/api/v1/agents", json={"name": "GateAgent"}, headers=hdr)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    # create permission request via ChatHandler pause path (direct)
    from src.agents.handlers.chat import ChatHandler
    from src.agents.handlers.base import AgentContext, AgentRequest

    me = (await app_client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()
    req = AgentRequest(entity_type="chat", conversation_id=ws["id"], message_id=str(uuid.uuid4()), agent_id=agent_id, workspace_id=ws["id"], triggering_user_id=me["id"])
    # need a real message row for message_id ref; skip — use uuid
    ctx = AgentContext(request=req, profile={"model": "test"}, session_ref=None, history=[{"sender_type": "user", "sender_id": req.triggering_user_id, "body": "hello"}], memories=[], model="test", env={})
    object.__setattr__(ctx, "_agent_perms", {"*", "workspace:update"})
    object.__setattr__(ctx, "_user_perms", {"*", "workspace:update"})
    h = ChatHandler()
    await h.pause_for_permission(req, ctx, tool="workspace.update", args={"name": "x"}, tool_call_id="tc1")

    # list
    lr = await app_client.get("/api/v1/agents/permission-requests", headers=hdr)
    assert lr.status_code == 200, lr.text
    assert any(p["tool_name"] == "workspace.update" and p["status"] == "pending" for p in lr.json())

    pending_id = next(p["id"] for p in lr.json() if p["tool_name"] == "workspace.update")
    dr = await app_client.post(f"/api/v1/agents/permission-requests/{pending_id}/decision", json={"approved": True}, headers=hdr)
    assert dr.status_code == 200, dr.text
    assert dr.json()["status"] == "approved"

    # expired path
    from datetime import datetime, timedelta, timezone

    from src.models.agent_permission import AgentPermissionRequest

    async with SessionFactory() as s:
        row = AgentPermissionRequest(workspace_id=ws["id"], conversation_id=ws["id"], agent_id=agent_id, triggering_user_id=req.triggering_user_id, run_message_id=str(uuid.uuid4()), tool_name="workspace.update", tool_call_id="tc-exp", args_summary={}, status="pending", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        exp_id = row.id
    er = await app_client.post(f"/api/v1/agents/permission-requests/{exp_id}/decision", json={"approved": True}, headers=hdr)
    assert er.status_code == 410, er.text


@pytest.mark.anyio
async def test_audit_per_tool_call(app_client):
    from src.mcp.platform.registry import _audit_tool_call  # type: ignore

    ws_id = str(uuid.uuid4())
    ag_id = str(uuid.uuid4())
    await _audit_tool_call(workspace_id=ws_id, agent_id=ag_id, tool_name="workspace.read", permission="workspace:read", outcome="success", triggering_user_id=ws_id, args_summary={"x": 1})
    async with SessionFactory() as s:
        from src.models.audit import AuditLogEntry

        rows = list((await s.execute(select(AuditLogEntry).where(AuditLogEntry.resource_type == "agent_tool", AuditLogEntry.resource_id == ag_id))).scalars().all())
        assert rows, "every platform tool call must create an audit_log_entries row"
        assert any(r.details.get("tool") == "workspace.read" for r in rows)
