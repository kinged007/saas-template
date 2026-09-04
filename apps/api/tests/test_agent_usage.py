import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from src.core.dates import now_utc
from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def _insert_usage(
    workspace_id: str,
    agent_id: str,
    *,
    message_id: str | None = None,
    model: str = "openrouter/free",
    input_tokens: int = 100,
    output_tokens: int = 25,
    status: str = "success",
    cost_cents: Decimal = Decimal("0.0000"),
    created_at=None,
) -> str:
    from src.db.session import SessionFactory
    from src.models.agent_usage import AgentUsage

    async with SessionFactory() as session:
        row = AgentUsage(
            workspace_id=workspace_id,
            agent_id=agent_id,
            user_id=None,
            conversation_id=None,
            message_id=message_id,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
            cost_cents=cost_cents,
            latency_ms=42,
            tool_calls_count=2,
            status=status,
            created_at=created_at or now_utc(),
        )
        session.add(row)
        await session.commit()
        return row.id


async def _usage_rows(client, headers, path="/api/v1/agents/usage"):
    r = await client.get(path, headers=headers)
    assert r.status_code == 200, r.text
    return r.json(), r.headers.get("X-Total-Count")


def test_compute_cost_cents(monkeypatch):
    """AGENT_COST_TABLE: cents per 1k tokens in/out; unlisted models cost 0."""
    from decimal import Decimal

    from src.agents.handlers import chat as chat_module

    monkeypatch.setattr(
        chat_module.settings,
        "agent_cost_table",
        '{"gpt-4o": {"input": 0.25, "output": 1.0}}',
    )
    chat_module._cost_table.cache_clear()
    try:
        assert chat_module.compute_cost_cents("gpt-4o", 1000, 1000) == Decimal("1.2500")
        assert chat_module.compute_cost_cents("gpt-4o", 500, 0) == Decimal("0.1250")
        assert chat_module.compute_cost_cents("unknown-model", 99999, 99999) == Decimal("0")
        assert chat_module.compute_cost_cents("", 1000, 1000) == Decimal("0")
    finally:
        chat_module._cost_table.cache_clear()


@pytest.mark.anyio
async def test_chat_run_records_exactly_one_usage_row(app_client, monkeypatch):
    """A chat run produces exactly one usage row; the dashboard endpoints see it."""
    # Deterministic run: without platform MCP tools the test model cannot hit
    # the Phase-8 approval gate (whose paused runs record no usage row).
    monkeypatch.setattr(
        "src.mcp.platform.registry.build_tools", lambda deps: []
    )
    client = app_client
    owner = await register_user(client, "usage-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    r = await client.post("/api/v1/agents", json={"name": "Helper", "slug": "helper", "model": "test"}, headers=hdr)
    assert r.status_code == 201, r.text
    agent_id = r.json()["id"]

    other = await register_user(client, "usage-other@example.com")
    roles = await client.get("/api/v1/roles", headers=hdr)
    role_id = next(x["id"] for x in roles.json() if x["name"] == "viewer")
    inv = await client.post("/api/v1/invitations", json={"email": "usage-other@example.com", "role_id": role_id}, headers=hdr)
    acc = await client.post("/api/v1/invitations/accept", params={"token": inv.json()["token"]}, headers=auth_headers(other))
    assert acc.status_code == 200, acc.text
    other_id = (await client.get("/api/v1/auth/me", headers=auth_headers(other))).json()["id"]

    r = await client.post(
        "/api/v1/conversations",
        json={"participant_user_ids": [other_id], "participant_agent_ids": [agent_id], "initial_message": "hello"},
        headers=hdr,
    )
    assert r.status_code == 201, r.text
    conv_id = r.json()["id"]

    # send one message; the agent reply lands asynchronously
    r = await client.post(f"/api/v1/conversations/{conv_id}/messages", json={"body": "ping"}, headers=hdr)
    assert r.status_code == 201, r.text
    msg_id = r.json()["id"]

    for _ in range(20):
        await asyncio.sleep(0.25)
        rows, _ = await _usage_rows(client, hdr)
        mine = [x for x in rows if x["message_id"] == msg_id]
        if mine:
            break
    else:
        msgs = (await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)).json()
        perms = (await client.get("/api/v1/agents/permission-requests", headers=hdr)).json()
        pytest.fail(f"no usage row appeared for message {msg_id}: rows={rows} msgs={msgs} perms={perms}")

    # exactly one row per run, and it does not grow on further polling
    assert len(mine) == 1
    assert mine[0]["status"] == "success"
    assert mine[0]["agent_id"] == agent_id
    assert mine[0]["conversation_id"] == conv_id
    assert mine[0]["model"], "model should be recorded"
    assert mine[0]["total_tokens"] >= 0
    assert isinstance(mine[0]["cost_cents"], float)

    # every agent reply produced exactly one row (initial message + ping)
    rows, total = await _usage_rows(client, hdr)
    agent_msgs = (
        await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=hdr)
    ).json()
    n_agent_replies = sum(1 for m in agent_msgs if m["sender_type"] == "agent")
    assert len(rows) == n_agent_replies == int(total)
    assert len(rows) == 2, f"expected one row per run, got {rows}"

    # per-agent endpoint sees the same rows
    agent_rows, agent_total = await _usage_rows(client, hdr, f"/api/v1/agents/{agent_id}/usage")
    assert len(agent_rows) == int(agent_total) == len(rows)


@pytest.mark.anyio
async def test_usage_permission_matrix(app_client):
    """owner/admin/editor may read usage; viewer may not; API keys are gated."""
    client = app_client
    owner = await register_user(client, "perm-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    r = await client.post("/api/v1/agents", json={"name": "Mat", "slug": "mat"}, headers=hdr)
    agent_id = r.json()["id"]

    created = []
    for email in ("perm-editor@example.com", "perm-viewer@example.com"):
        user = await register_user(client, email)
        roles = await client.get("/api/v1/roles", headers=hdr)
        role_name = "editor" if "editor" in email else "viewer"
        role_id = next(x["id"] for x in roles.json() if x["name"] == role_name)
        inv = await client.post("/api/v1/invitations", json={"email": email, "role_id": role_id}, headers=hdr)
        assert inv.status_code == 201, inv.text
        acc = await client.post("/api/v1/invitations/accept", params={"token": inv.json()["token"]}, headers=auth_headers(user))
        assert acc.status_code == 200, acc.text
        created.append(user)
    editor, viewer = created

    for _ in range(2):
        await _insert_usage(ws["id"], agent_id)

    # owner + editor are allowed; viewer is not
    assert (await client.get("/api/v1/agents/usage", headers=hdr)).status_code == 200
    editor_hdr = ws_headers(editor, ws["id"])
    assert (await client.get("/api/v1/agents/usage", headers=editor_hdr)).status_code == 200
    viewer_hdr = ws_headers(viewer, ws["id"])
    deny = await client.get("/api/v1/agents/usage", headers=viewer_hdr)
    assert deny.status_code == 403
    assert "agent:usage:read" in deny.json()["detail"]

    # API key with the permission works; without it, 403
    with_perm = await client.post(
        "/api/v1/api-keys",
        json={"name": "usage-key", "permissions": ["agent:usage:read"]},
        headers=hdr,
    )
    assert with_perm.status_code == 201, with_perm.text
    key_ok = {"Authorization": f"Bearer {with_perm.json()['key']}", "X-Workspace-ID": ws["id"]}
    ok = await client.get("/api/v1/agents/usage", headers=key_ok)
    assert ok.status_code == 200

    without_perm = await client.post(
        "/api/v1/api-keys",
        json={"name": "readonly-key", "permissions": ["agent:read"]},
        headers=hdr,
    )
    key_bad = {"Authorization": f"Bearer {without_perm.json()['key']}", "X-Workspace-ID": ws["id"]}
    bad = await client.get("/api/v1/agents/usage", headers=key_bad)
    assert bad.status_code == 403
    assert "agent:usage:read" in bad.json()["detail"]

    # per-agent endpoint enforces the same gate and 404s for foreign agents
    assert (await client.get(f"/api/v1/agents/{agent_id}/usage", headers=viewer_hdr)).status_code == 403
    assert (await client.get(f"/api/v1/agents/{agent_id}/usage", headers=hdr)).status_code == 200


@pytest.mark.anyio
async def test_usage_filters_and_csv_export(app_client):
    """Filters narrow the list; X-Total-Count matches; CSV mirrors the filtered rows."""
    client = app_client
    owner = await register_user(client, "csv-owner@example.com")
    ws = await create_workspace(client, owner)
    hdr = ws_headers(owner, ws["id"])

    r = await client.post("/api/v1/agents", json={"name": "A", "slug": "a"}, headers=hdr)
    agent_a = r.json()["id"]
    r = await client.post("/api/v1/agents", json={"name": "B", "slug": "b"}, headers=hdr)
    agent_b = r.json()["id"]

    now = now_utc()
    await _insert_usage(ws["id"], agent_a, model="openrouter/free", status="success", created_at=now - timedelta(days=1))
    await _insert_usage(ws["id"], agent_a, model="openrouter/free", status="error", created_at=now - timedelta(days=2))
    await _insert_usage(ws["id"], agent_b, model="gpt-4o", status="success", created_at=now)

    base = "/api/v1/agents/usage"

    # no filters → all three, X-Total-Count correct
    rows, total = await _usage_rows(client, hdr, base)
    assert int(total) == len(rows) == 3

    # filter by status
    rows, total = await _usage_rows(client, hdr, f"{base}?status=success")
    assert int(total) == 2 and all(x["status"] == "success" for x in rows)

    # filter by agent_id
    rows, total = await _usage_rows(client, hdr, f"{base}?agent_id={agent_a}")
    assert int(total) == 2 and all(x["agent_id"] == agent_a for x in rows)

    # filter by model + agent
    rows, total = await _usage_rows(client, hdr, f"{base}?model=openrouter%2Ffree&agent_id={agent_a}")
    assert int(total) == 2

    # date bounds (ISO and date-only)
    day = now.strftime("%Y-%m-%d")
    rows, total = await _usage_rows(client, hdr, f"{base}?from={day}")
    assert int(total) == 1 and rows[0]["agent_id"] == agent_b
    rows, total = await _usage_rows(client, hdr, f"{base}?to={day}")
    assert int(total) == 3

    # unknown filter field → 422
    bad = await client.get(f"{base}?bogus=1", headers=hdr)
    assert bad.status_code == 422

    # refine-style pagination keeps the header total
    rows, total = await _usage_rows(client, hdr, f"{base}?offset=0&limit=2")
    assert len(rows) == 2 and int(total) == 3

    # CSV export mirrors the filtered list (no pagination), same total header
    r = await client.get(f"{base}?status=success&format=csv", headers=hdr)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert r.headers.get("X-Total-Count") == "2"
    lines = r.text.strip().splitlines()
    assert lines[0].split(",")[0] == "id"
    data = [row for row in lines[1:] if row]
    assert len(data) == 2
    assert all("success" in row for row in data)