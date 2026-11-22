"""Project extension seams (#1794): the demo feature under `src/project/`.

Covers AC-1 (router + model + setting + workflow + job + permission served,
migrated and authorized with zero template-owned edits) and AC-3 (template
subscriptions still registered; project `register_workflows` gets the shared
registry and bus). Fail-fast loading is covered without booting the app.
"""

import pytest

from src.extensions import (
    extension_module_names,
    load_extension_models,
    load_extension_modules,
)
from src.jobs.registry import job_registry
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)


async def _add_member(client, owner_tokens, ws, email: str, role_name: str):
    roles = (await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))).json()
    role = next(r for r in roles if r["name"] == role_name)
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": email, "role_id": role["id"]},
            headers=ws_headers(owner_tokens, ws["id"]),
        )
    ).json()
    user = await register_user(client, email)
    resp = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    return user


async def test_demo_widgets_served_and_authorized(app_client):
    client = app_client
    owner = await register_user(client, "demo-owner@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    viewer = await _add_member(client, owner, ws, "demo-viewer@example.com", "viewer")

    # Served: the project setting rides along with the empty list.
    resp = await client.get("/api/v1/demo/widgets", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"message": "hello from the project extension", "widgets": []}

    # Authorized: viewer (no demo permission) is denied, owner (star) passes.
    resp = await client.get("/api/v1/demo/widgets", headers=ws_headers(viewer, ws["id"]))
    assert resp.status_code == 403, resp.text

    # Model: created rows persist and list back workspace-scoped.
    resp = await client.post("/api/v1/demo/widgets", json={"name": "first"}, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "first"
    resp = await client.get("/api/v1/demo/widgets", headers=headers)
    assert [w["name"] for w in resp.json()["widgets"]] == ["first"]


async def test_demo_permissions_assignable_to_roles(app_client):
    client = app_client
    owner = await register_user(client, "demo-perm-owner@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    catalog = (await client.get("/api/v1/roles/permission-catalog", headers=headers)).json()
    assert "demo:read" in catalog["catalog"]
    assert "demo:create" in catalog["catalog"]

    resp = await client.post(
        "/api/v1/roles",
        json={"name": "demo-ops", "permissions": ["demo:read", "demo:create"]},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text

    member = await _add_member(client, owner, ws, "demo-ops@example.com", "demo-ops")
    resp = await client.get("/api/v1/demo/widgets", headers=ws_headers(member, ws["id"]))
    assert resp.status_code == 200, resp.text


async def test_demo_job_registered_and_provisioned(app_client):
    client = app_client
    assert job_registry.get("demo.heartbeat") is not None

    tokens = await register_user(client, "root@example.com")
    assert tokens  # SUPERADMIN_EMAIL bootstrap (conftest pins it)
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["is_superuser"] is True
    resp = await client.get("/api/v1/jobs/global", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    assert "demo.heartbeat" in {j["key"] for j in resp.json()}


async def test_demo_workflows_registered_with_template_ones():
    from src.events.factory import WorkflowRegistry
    from src.project.workflows import DEMO_PING, received
    from src.workflows import build_workflows
    from tests.bus_doubles import ReplayBus

    received.clear()
    bus = ReplayBus()
    registry = WorkflowRegistry(bus)
    build_workflows(registry, bus, None, None)

    from src.project.workflows import register_workflows as project_register

    project_register(registry, bus, None, None)
    assert DEMO_PING in registry.subjects
    # AC-3: template subscriptions are still registered alongside the project one.
    assert "workspaces.member.joined" in registry.subjects

    await bus.start()
    try:
        await registry.wire()
        await bus.publish(DEMO_PING, {"hello": "demo"})
        assert {"hello": "demo"} in received
    finally:
        await bus.stop()
        await registry.stop()


def test_extension_module_names_default():
    assert extension_module_names() == ["src.project"]


def test_extension_load_failure_is_loud(monkeypatch):
    from src import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "extension_modules", "src.nonexistent_ext_xyz")
    with pytest.raises(RuntimeError, match="src.nonexistent_ext_xyz"):
        load_extension_modules()
    with pytest.raises(RuntimeError, match="src.nonexistent_ext_xyz"):
        load_extension_models()


def test_empty_extension_modules_loads_nothing(monkeypatch):
    from src import settings as settings_module

    monkeypatch.setattr(settings_module.settings, "extension_modules", "")
    assert extension_module_names() == []
    assert load_extension_modules() == []
    load_extension_models()  # must not raise


async def test_demo_rows_deleted_with_workspace(app_client):
    from sqlalchemy import func, select

    from src.db.session import SessionFactory
    from src.project.models import DemoWidget

    client = app_client
    owner = await register_user(client, "demo-cascade-owner@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    resp = await client.post("/api/v1/demo/widgets", json={"name": "doomed"}, headers=headers)
    assert resp.status_code == 201, resp.text

    resp = await client.delete("/api/v1/workspaces/" + ws["id"], headers=headers)
    assert resp.status_code == 204, resp.text

    async with SessionFactory() as session:
        remaining = (
            await session.execute(
                select(func.count())
                .select_from(DemoWidget)
                .where(DemoWidget.workspace_id == ws["id"])
            )
        ).scalar_one()
    assert remaining == 0
