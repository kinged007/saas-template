"""Scheduled jobs framework: provisioning, permissions, execution, capture."""

import asyncio
import logging

from src.core.dates import ensure_utc
from src.jobs.registry import JobSpec, job_registry
from tests.conftest import (
    auth_headers,
    create_workspace,
    login,
    register_user,
    run_job_via_scheduler,
    ws_headers,
)

# ---------------------------------------------------------------------------
# Test jobs. Registered once at collection; every app_client startup
# provisions their definition rows via sync_definitions.
# ---------------------------------------------------------------------------


@job_registry.register(
    JobSpec(
        key="test.echo",
        name="Echo (test)",
        description="Writes the configured greeting to stdout and logging.",
        scope="workspace",
        schedule="0 6 * * *",
        params_schema={
            "greeting": {"type": "string", "default": "hello", "max_length": 50},
            "retries": {"type": "int", "default": 3, "min": 1, "max": 10},
            "ratio": {"type": "float", "default": 0.5},
            "start_day": {"type": "date", "default": "2026-01-01"},
            "secret": {"type": "password", "default": None},
        },
        default_enabled=False,
        missed_policy="single",
        timeout_seconds=60,
    )
)
async def _echo(ctx) -> None:
    print(f"echo: {ctx.params.get('greeting')}")
    logging.getLogger("test.echo").info("logged line from echo")
    await asyncio.sleep(0.05)


@job_registry.register(
    JobSpec(
        key="test.boom",
        name="Boom (test)",
        description="Always fails.",
        scope="global",
        schedule="0 7 * * *",
        params_schema={},
        default_enabled=False,
        missed_policy="ignore",
        timeout_seconds=60,
    )
)
async def _boom(ctx) -> None:
    raise RuntimeError("boom!")


async def wait_for_terminal(client, headers, run_id, timeout_s=10.0):
    for _ in range(int(timeout_s * 10)):
        resp = await client.get(f"/api/v1/jobs/runs/{run_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        data = resp.json()
        if data["status"] in ("success", "failed", "timed_out"):
            return data
        await asyncio.sleep(0.1)
    raise AssertionError(f"run {run_id} did not finish in time")


def _by_key(jobs, key):
    return next(j for j in jobs if j["key"] == key)


# --------------------------------------------------------------------- setup


async def setup_workspace(client, email, *, ws_name=None):
    owner = await register_user(client, email)
    ws = await create_workspace(client, owner, name=ws_name or f"WS {email.split('@')[0]}")
    headers = ws_headers(owner, ws["id"])
    roles = await client.get("/api/v1/roles", headers=headers)
    # Workspace-scoped definitions arrive asynchronously via the
    # workspaces.created workflow — wait for the provisioning to land.
    for _ in range(50):
        resp = await client.get("/api/v1/jobs", headers=headers)
        if any(j["key"] == "test.echo" for j in resp.json()):
            break
        await asyncio.sleep(0.1)
    return owner, ws, headers, {r["name"]: r["id"] for r in roles.json()}


async def invite_and_accept(client, owner_headers, owner_ws, roles, role_name, email):
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": roles[role_name]},
        headers=owner_headers,
    )
    invite = invite.json()
    member = await register_user(client, email)
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member),
    )
    return member


# -------------------------------------------------------------------- tests


async def test_startup_provisions_workspace_and_global_jobs(app_client):
    client = app_client
    owner, ws, headers, _ = await setup_workspace(client, "jobs-owner@example.com")

    resp = await client.get("/api/v1/jobs", headers=headers)
    assert resp.status_code == 200
    keys = {j["key"] for j in resp.json()}
    assert "test.echo" in keys
    assert "demo.workspace_report" in keys
    # the expiry job is global now, so it is not in the workspace list
    assert "invitations.expire_stale" not in keys
    # workspace list never contains global jobs
    assert "system.heartbeat" not in keys
    assert all(j["scope"] == "workspace" for j in resp.json())
    assert all(j["workspace_id"] == ws["id"] for j in resp.json())

    # a second workspace gets its own independent rows
    other = await create_workspace(client, owner, name="Second")
    other_headers = ws_headers(owner, other["id"])
    other_jobs = []
    for _ in range(50):
        other_jobs = (await client.get("/api/v1/jobs", headers=other_headers)).json()
        if any(j["key"] == "test.echo" for j in other_jobs):
            break
        await asyncio.sleep(0.1)
    other_echo = _by_key(other_jobs, "test.echo")
    first_echo = _by_key(resp.json(), "test.echo")
    assert other_echo["id"] != first_echo["id"]
    assert other_echo["workspace_id"] == other["id"]


async def test_global_jobs_require_superuser(app_client):
    client = app_client
    await register_user(client, "plain@example.com")
    tokens = await register_user(client, "root@example.com")  # SUPERADMIN_EMAIL account

    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["is_superuser"] is True

    resp = await client.get("/api/v1/jobs/global", headers=auth_headers(tokens))
    assert resp.status_code == 200
    keys = {j["key"] for j in resp.json()}
    assert "system.heartbeat" in keys
    assert "test.boom" in keys
    # enabled by default so a deployment expires invitations without setup
    expire = _by_key(resp.json(), "invitations.expire_stale")
    assert expire["scope"] == "global" and expire["enabled"] is True
    assert all(j["workspace_id"] is None for j in resp.json())

    # non-superusers are rejected
    plain = await login(client, "plain@example.com")
    denied = await client.get("/api/v1/jobs/global", headers=auth_headers(plain))
    assert denied.status_code == 403


async def test_global_execute_of_a_workspace_definition_is_unaffected(app_client):
    """The /jobs/global execute route resolves its definition with no
    workspace filter, so a superuser may run a workspace-owned definition
    through it; an id that matches nothing is still the 404. Pins the
    behaviour of `_admin_definition_or_404` once its cross-workspace branch
    was dead code and removed. Regression test for #1121.
    """
    import uuid

    client = app_client
    owner, _, headers, _ = await setup_workspace(client, "globalrun-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    tokens = await register_user(client, "root@example.com")  # SUPERADMIN_EMAIL account
    gh = auth_headers(tokens)

    resp = await client.post(f"/api/v1/jobs/global/{job['id']}/execute", json={}, headers=gh)
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["definition_id"] == job["id"], run
    # The run belongs to the definition's workspace, so the superuser cannot
    # read it back — the workspace owner can, and it really executed.
    finished = await wait_for_terminal(client, auth_headers(owner), run["id"])
    assert finished["status"] == "success", finished

    missing = await client.post(f"/api/v1/jobs/global/{uuid.uuid4()}/execute", json={}, headers=gh)
    assert missing.status_code == 404, missing.text
    assert missing.json()["detail"] == "job not found"


async def test_registration_grants_superuser_only_to_configured_email(app_client):
    client = app_client
    tokens = await register_user(client, "root@example.com")
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["is_superuser"] is True
    other = await register_user(client, "not-root@example.com")
    me2 = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    assert me2.json()["is_superuser"] is False


async def test_job_permission_matrix(app_client):
    client = app_client
    _, ws, owner_headers, roles = await setup_workspace(client, "matrix-owner@example.com")
    editor = await invite_and_accept(
        client, owner_headers, ws, roles, "editor", "matrix-editor@example.com"
    )
    viewer = await invite_and_accept(
        client, owner_headers, ws, roles, "viewer", "matrix-viewer@example.com"
    )
    editor_headers = ws_headers(editor, ws["id"])
    viewer_headers = ws_headers(viewer, ws["id"])

    job = _by_key((await client.get("/api/v1/jobs", headers=owner_headers)).json(), "test.echo")

    # viewer has no jobs:read: cannot read...
    assert (await client.get("/api/v1/jobs", headers=viewer_headers)).status_code == 403
    assert (
        await client.get(f"/api/v1/jobs/{job['id']}", headers=viewer_headers)
    ).status_code == 403
    # ...edit or execute
    patch = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"enabled": True}, headers=viewer_headers
    )
    assert patch.status_code == 403
    execute = await client.post(f"/api/v1/jobs/{job['id']}/execute", headers=viewer_headers)
    assert execute.status_code == 403

    # editor also lacks jobs:read by default
    assert (await client.get("/api/v1/jobs", headers=editor_headers)).status_code == 403
    patch = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"enabled": True}, headers=editor_headers
    )
    assert patch.status_code == 403

    # owner can edit and execute
    patch = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"enabled": True, "cron_schedule": "*/10 * * * *"},
        headers=owner_headers,
    )
    assert patch.status_code == 200
    body = patch.json()
    assert body["enabled"] is True
    assert body["cron_schedule"] == "*/10 * * * *"
    assert body["next_run_at"] is not None


async def test_admin_can_view_and_edit_jobs(app_client):
    """Admins are the default role holding jobs:read / jobs:update."""
    from src.core.permissions import JOB_READ, JOB_UPDATE

    client = app_client
    _, ws, owner_headers, roles = await setup_workspace(client, "adminjobs-owner@example.com")
    admin = await invite_and_accept(
        client, owner_headers, ws, roles, "admin", "adminjobs-admin@example.com"
    )
    admin_headers = ws_headers(admin, ws["id"])

    membership_role = next(
        r
        for r in (await client.get("/api/v1/roles", headers=admin_headers)).json()
        if r["name"] == "admin"
    )
    assert JOB_READ in membership_role["permissions"]
    assert JOB_UPDATE in membership_role["permissions"]

    job = _by_key((await client.get("/api/v1/jobs", headers=admin_headers)).json(), "test.echo")
    assert (await client.get(f"/api/v1/jobs/{job['id']}", headers=admin_headers)).status_code == 200
    patch = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"enabled": True}, headers=admin_headers
    )
    assert patch.status_code == 200
    execute = await client.post(f"/api/v1/jobs/{job['id']}/execute", json={}, headers=admin_headers)
    assert execute.status_code == 201


async def test_patch_validates_params_and_cron(app_client):
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "validate-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    bad_cron = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"cron_schedule": "not a cron"}, headers=headers
    )
    assert bad_cron.status_code == 422

    bad_int = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"params": {"retries": "many"}},
        headers=headers,
    )
    assert bad_int.status_code == 422

    out_of_range = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"params": {"retries": 99}}, headers=headers
    )
    assert out_of_range.status_code == 422

    unknown = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"params": {"nope": 1}}, headers=headers
    )
    assert unknown.status_code == 422

    bad_date = await client.patch(
        f"/api/v1/jobs/{job['id']}", json={"params": {"start_day": "tomorrow"}}, headers=headers
    )
    assert bad_date.status_code == 422

    ok = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"params": {"retries": 5, "ratio": "0.75"}},
        headers=headers,
    )
    assert ok.status_code == 200
    params = ok.json()["params"]
    assert params["retries"] == 5
    assert params["ratio"] == 0.75  # coerced from string
    assert params["greeting"] == "hello"  # unspecified keeps stored value


async def test_password_param_roundtrip_is_masked(app_client):
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "secret-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    patched = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"params": {"secret": "hunter2"}},
        headers=headers,
    )
    assert patched.status_code == 200
    masked = patched.json()["params"]["secret"]
    assert masked not in (None, "", "hunter2")  # mask sentinel, never plaintext

    # sending the mask back keeps the stored value; detail view stays masked
    again = await client.patch(
        f"/api/v1/jobs/{job['id']}",
        json={"params": {"secret": masked}},
        headers=headers,
    )
    assert again.status_code == 200
    assert again.json()["params"]["secret"] == masked

    from src.core.security.crypto import SecretCipher
    from src.db.session import SessionFactory
    from src.models.jobs import JobDefinition
    from src.settings import settings

    cipher = SecretCipher(settings.fernet_key_list)
    async with SessionFactory() as session:
        row = await session.get(JobDefinition, job["id"])
        stored = row.params["secret"]
        assert stored != "hunter2"
        assert cipher.decrypt(stored) == "hunter2"


async def test_execute_now_runs_and_captures_logs(app_client):
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "exec-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    resp = await client.post(
        f"/api/v1/jobs/{job['id']}/execute",
        json={},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["trigger"] == "manual"
    assert run["status"] == "pending"

    finished = await wait_for_terminal(client, headers, run["id"])
    assert finished["status"] == "success"
    assert finished["duration_ms"] is not None
    assert finished["actor_user_id"] is not None

    # last_run_at reflects the actual execution start (manual runs included)
    detail = await client.get(f"/api/v1/jobs/{job['id']}", headers=headers)
    assert detail.json()["last_run_at"] is not None

    logs = await client.get(f"/api/v1/jobs/runs/{run['id']}/logs", headers=headers)
    assert logs.status_code == 200
    messages = [e["message"] for e in logs.json()]
    assert any("echo: hello" in m for m in messages), messages  # print() captured
    assert any("logged line from echo" in m for m in messages), messages  # logging captured


async def test_failed_run_records_error(app_client):
    client = app_client
    tokens = await register_user(client, "root@example.com")
    headers = auth_headers(tokens)
    jobs = (await client.get("/api/v1/jobs/global", headers=headers)).json()
    boom = _by_key(jobs, "test.boom")

    resp = await client.post(f"/api/v1/jobs/global/{boom['id']}/execute", json={}, headers=headers)
    run = resp.json()
    finished = await wait_for_terminal(client, headers, run["id"])
    assert finished["status"] == "failed"
    assert "RuntimeError" in finished["error"]
    assert "boom!" in finished["error"]


async def test_double_claim_is_prevented(app_client):
    """A run already terminal must not be re-executed by a redelivered message."""
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.jobs.executor import execute_run
    from src.models.jobs import JobDefinition, JobRun

    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "claim-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    run_resp = await client.post(f"/api/v1/jobs/{job['id']}/execute", json={}, headers=headers)
    run_id = run_resp.json()["id"]
    finished = await wait_for_terminal(client, headers, run_id)
    assert finished["status"] == "success"

    async with SessionFactory() as session:
        count_before = len(
            (await session.execute(select(JobRun).where(JobRun.definition_id == job["id"])))
            .scalars()
            .all()
        )

    # redelivery: claim CAS fails because the run is no longer pending
    await execute_run(run_id)

    async with SessionFactory() as session:
        runs = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == job["id"])))
            .scalars()
            .all()
        )
        assert len(runs) == count_before
        row = next(r for r in runs if r.id == run_id)
        assert row.status == "success"

    # also: an already-claimed (running) run cannot be claimed twice
    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, job["id"])
        session.add(
            JobRun(
                definition_id=definition.id,
                workspace_id=None,
                status="running",
                scheduled_at=definition.created_at,
            )
        )
        await session.commit()


async def test_scheduler_claims_due_occurrence_atomically(app_client):
    from datetime import timedelta

    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.jobs import JobDefinition, JobRun
    from src.services.jobs import JobService

    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "sched-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, job["id"])
        definition.enabled = True
        from src.core.dates import now_utc

        definition.next_run_at = now_utc() - timedelta(seconds=5)
        await session.commit()

    async with SessionFactory() as session:
        scheduled = await JobService(session).schedule_due()
    assert scheduled == 1

    async with SessionFactory() as session:
        runs = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == job["id"])))
            .scalars()
            .all()
        )
        assert len(runs) == 1
        refreshed = await session.get(JobDefinition, job["id"])
        assert ensure_utc(refreshed.next_run_at) > now_utc()

    # second tick for the same occurrence must NOT schedule again
    async with SessionFactory() as session:
        scheduled_again = await JobService(session).schedule_due()
    assert scheduled_again == 0
    async with SessionFactory() as session:
        runs = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == job["id"])))
            .scalars()
            .all()
        )
        assert len(runs) == 1


async def test_missed_ignore_policy_skips_catchup(app_client):
    from datetime import timedelta

    from sqlalchemy import select

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.models.jobs import JobDefinition, JobRun
    from src.services.jobs import JobService

    client = app_client
    tokens = await register_user(client, "root@example.com")
    headers = auth_headers(tokens)
    jobs = (await client.get("/api/v1/jobs/global", headers=headers)).json()
    boom = _by_key(jobs, "test.boom")  # registered with missed_policy=ignore

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, boom["id"])
        definition.enabled = True
        definition.next_run_at = now_utc() - timedelta(hours=3)  # clearly missed
        await session.commit()

    async with SessionFactory() as session:
        scheduled = await JobService(session).schedule_due()
    assert scheduled == 0

    async with SessionFactory() as session:
        runs = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == boom["id"])))
            .scalars()
            .all()
        )
        assert runs == []
        refreshed = await session.get(JobDefinition, boom["id"])
        assert refreshed.next_run_at is not None  # still advanced


async def test_missed_single_policy_fires_once(app_client):
    from datetime import timedelta

    from sqlalchemy import select

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.models.jobs import JobDefinition, JobRun
    from src.services.jobs import JobService

    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "catchup-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    async with SessionFactory() as session:
        definition = await session.get(JobDefinition, job["id"])
        definition.enabled = True
        definition.next_run_at = now_utc() - timedelta(hours=3)
        await session.commit()

    async with SessionFactory() as session:
        scheduled = await JobService(session).schedule_due()
    assert scheduled == 1
    async with SessionFactory() as session:
        runs = (
            (await session.execute(select(JobRun).where(JobRun.definition_id == job["id"])))
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert ensure_utc(runs[0].scheduled_at) < now_utc() - timedelta(hours=2)


async def test_workspace_isolation_on_definitions_and_runs(app_client):
    client = app_client
    owner_a, ws_a, headers_a, _ = await setup_workspace(client, "iso-a@example.com")
    owner_b, ws_b, headers_b, _ = await setup_workspace(client, "iso-b@example.com")

    job_a = _by_key((await client.get("/api/v1/jobs", headers=headers_a)).json(), "test.echo")

    # a non-member is refused with 403, the answer the run routes already give
    for method, url, body in (
        ("get", f"/api/v1/jobs/{job_a['id']}", None),
        ("patch", f"/api/v1/jobs/{job_a['id']}", {"enabled": True}),
        ("post", f"/api/v1/jobs/{job_a['id']}/execute", {}),
    ):
        resp = await client.request(method, url, json=body, headers=headers_b)
        assert resp.status_code == 403, resp.text
        assert resp.json()["detail"] == "you are not a member of this workspace"

    # B's own list shows a different row with the same key
    job_b = _by_key((await client.get("/api/v1/jobs", headers=headers_b)).json(), "test.echo")
    assert job_a["id"] != job_b["id"]

    run = await client.post(f"/api/v1/jobs/{job_a['id']}/execute", json={}, headers=headers_a)
    run_id = run.json()["id"]
    outsider = await register_user(client, "iso-outsider@example.com")
    resp = await client.get(f"/api/v1/jobs/runs/{run_id}", headers=auth_headers(outsider))
    assert resp.status_code == 403
    assert resp.json()["detail"] == "you are not a member of this workspace"


async def test_run_routes_refuse_non_member_and_role_without_jobs_read(app_client):
    """Pins the run routes' session branch: 403, with the membership and the
    permission message distinguished."""
    client = app_client
    _, ws, owner_headers, roles = await setup_workspace(client, "runaccess-owner@example.com")
    viewer = await invite_and_accept(
        client, owner_headers, ws, roles, "viewer", "runaccess-viewer@example.com"
    )
    outsider = await register_user(client, "runaccess-outsider@example.com")

    job = _by_key((await client.get("/api/v1/jobs", headers=owner_headers)).json(), "test.echo")
    run_id = (
        await client.post(f"/api/v1/jobs/{job['id']}/execute", json={}, headers=owner_headers)
    ).json()["id"]

    for headers, detail in (
        (auth_headers(outsider), "you are not a member of this workspace"),
        (ws_headers(viewer, ws["id"]), "missing permission: jobs:read"),
    ):
        for url in (f"/api/v1/jobs/runs/{run_id}", f"/api/v1/jobs/runs/{run_id}/logs"):
            resp = await client.get(url, headers=headers)
            assert resp.status_code == 403, (url, resp.status_code, resp.text)
            assert resp.json()["detail"] == detail, url

    # the refusals changed nothing: the owner still reads the same run and its
    # logs, and the run is still the one recorded for the definition. Asserting
    # membership rather than an exact count — the scheduler may fire in parallel.
    owner_run = await client.get(f"/api/v1/jobs/runs/{run_id}", headers=owner_headers)
    assert owner_run.status_code == 200, owner_run.text
    assert owner_run.json()["id"] == run_id
    assert owner_run.json()["workspace_id"] == ws["id"]
    assert (
        await client.get(f"/api/v1/jobs/runs/{run_id}/logs", headers=owner_headers)
    ).status_code == 200
    runs = await client.get(f"/api/v1/jobs/{job['id']}/runs", headers=owner_headers)
    assert run_id in [r["id"] for r in runs.json()], runs.text


async def test_new_workspace_gets_jobs_via_event(app_client):
    """Creating a workspace provisions its job rows through workspaces.created."""
    import asyncio

    client = app_client
    owner = await register_user(client, "provision@example.com")
    ws = await create_workspace(client, owner, name="Provisioned")
    headers = ws_headers(owner, ws["id"])

    for _ in range(30):  # wait for the event-driven provisioning to land
        resp = await client.get("/api/v1/jobs", headers=headers)
        if any(j["key"] == "test.echo" for j in resp.json()):
            break
        await asyncio.sleep(0.1)
    assert any(j["key"] == "test.echo" for j in resp.json())


async def test_runs_history_pagination(app_client):
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "history-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    for _ in range(3):
        resp = await client.post(f"/api/v1/jobs/{job['id']}/execute", json={}, headers=headers)
        assert resp.status_code == 201

    resp = await client.get(
        f"/api/v1/jobs/{job['id']}/runs?limit=2&offset=0",
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "3"
    assert len(resp.json()) == 2


async def test_runs_list_masks_params_from_the_definition_schema(app_client):
    """Run rows on the history endpoints are serialized with the
    params_schema of the definition the caller already resolved —
    `_list_runs` itself does no definition read (#1310). Pins the row-level
    passthrough on both call sites: the workspace route, and the superuser
    /global route over a workspace-owned definition (a `/global*` id may
    name a workspace-owned definition by design)."""
    import uuid

    from sqlalchemy import select

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.jobs.registry import PASSWORD_MASK
    from src.models.jobs import JobDefinition, JobRun, JobRunStatus, JobTrigger

    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "runs-mask-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    # Insert runs directly: test.echo has enabled=False, and the row-level
    # serialization — not the execution path — is what is under test.
    async with SessionFactory() as session:
        definition = (
            await session.execute(select(JobDefinition).where(JobDefinition.id == job["id"]))
        ).scalar_one()
        params = {"greeting": "hi", "retries": 3, "secret": "plaintext-secret"}
        stamp = now_utc()
        for _ in range(2):
            session.add(
                JobRun(
                    id=str(uuid.uuid4()),
                    definition_id=definition.id,
                    workspace_id=definition.workspace_id,
                    status=JobRunStatus.SUCCESS.value,
                    trigger=JobTrigger.MANUAL.value,
                    params=params,
                    scheduled_at=stamp,
                    created_at=stamp,
                    updated_at=stamp,
                )
            )
        await session.commit()

    resp = await client.get(f"/api/v1/jobs/{definition.id}/runs", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["X-Total-Count"] == "2"
    for row in resp.json():
        # The schema rides on the definition the route resolved — a
        # password-typed field must come back masked, non-password fields
        # in the clear.
        assert row["params"]["secret"] == PASSWORD_MASK
        assert row["params"]["greeting"] == "hi"
        assert row["params"]["retries"] == 3

    tokens = await register_user(client, "root@example.com")  # SUPERADMIN_EMAIL account
    resp = await client.get(
        f"/api/v1/jobs/global/{definition.id}/runs",
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200, resp.text
    assert [r["params"]["secret"] for r in resp.json()] == [PASSWORD_MASK] * 2


async def test_global_runs_of_a_missing_definition_404(app_client):
    """The /global runs route resolves the definition up front, like its
    execute/get/patch siblings, so an id that matches nothing is a 404 —
    not a 200 with an empty list (#1310)."""
    import uuid

    client = app_client
    tokens = await register_user(client, "root@example.com")  # SUPERADMIN_EMAIL account
    resp = await client.get(
        f"/api/v1/jobs/global/{uuid.uuid4()}/runs",
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 404


async def test_scheduled_tick_with_bus_executes_via_worker(app_client):
    """Regression: scheduler tick must publish jobs.execute so the worker picks it up.

    Before the fix, JobScheduler.tick() used JobService(session) without a bus,
    so schedule_due() created a pending JobRun but never published jobs.execute.
    The run stayed pending until fail_stale_runs marked it
    'abandoned: no worker completed this run'. Driving the app's real scheduler
    through the shared harness pins the production wiring: the scheduled run
    reaches success with its logs, and the tick claims the occurrence exactly
    once.
    """
    client = app_client
    _, ws, headers, _ = await setup_workspace(client, "sched-bus-owner@example.com")
    job = _by_key((await client.get("/api/v1/jobs", headers=headers)).json(), "test.echo")

    patch = await client.patch(f"/api/v1/jobs/{job['id']}", json={"enabled": True}, headers=headers)
    assert patch.status_code == 200, patch.text

    run, messages = await run_job_via_scheduler("test.echo", workspace_id=ws["id"])

    assert run.trigger == "scheduled"
    assert run.status == "success", run.error
    assert any("echo: hello" in m for m in messages), messages
    runs = await client.get(f"/api/v1/jobs/{job['id']}/runs", headers=headers)
    assert [r["id"] for r in runs.json()] == [run.id], runs.text


async def test_expire_invitations_purges_only_invitations_expired_over_30_days(app_client):
    """The global expiry job marks stale pending invites, then purges aged ones.

    The purge window is measured from expires_at, not from when the job marked
    the row: there is no "marked at" column, and an invitation that is 31 days
    past its expiry has been expired for 31 days.
    """
    from datetime import timedelta

    from sqlalchemy import select

    from src.core.dates import now_utc
    from src.db.session import SessionFactory
    from src.jobs.builtin import INVITATION_EXPIRED_RETENTION_DAYS, expire_stale_invitations
    from src.jobs.registry import JobContext
    from src.models.core import Invitation

    owner, ws, _headers, roles = await setup_workspace(app_client, "purge@example.com")
    now = now_utc()
    aged = timedelta(days=INVITATION_EXPIRED_RETENTION_DAYS + 10)
    me = (await app_client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()
    role_id, inviter = next(iter(roles.values())), me["id"]

    def invitation(email: str, token: str, status: str, expires_at):
        return Invitation(
            workspace_id=ws["id"],
            email=email,
            role_id=role_id,
            invited_by_user_id=inviter,
            token=token,
            status=status,
            expires_at=expires_at,
        )

    async with SessionFactory() as session:
        session.add_all(
            [
                # pending and long past expiry: marked, and aged past the window
                # so the same run purges it
                invitation("aged@example.com", "purge-aged", "pending", now - aged),
                # pending but only just past expiry: marked, kept
                invitation("fresh@example.com", "purge-fresh", "pending", now - timedelta(days=2)),
                # marked on an earlier run, expiry inside the window: kept
                invitation(
                    "recent@example.com", "purge-recent", "expired", now - timedelta(days=1)
                ),
                # pending, not yet expired: untouched
                invitation("valid@example.com", "purge-valid", "pending", now + timedelta(days=3)),
            ]
        )
        await session.commit()

    await expire_stale_invitations(
        JobContext(
            run_id="purge-run", job_key="invitations.expire_stale", workspace_id=None, params={}
        )
    )

    async with SessionFactory() as session:
        remaining = {
            i.email: i.status for i in (await session.execute(select(Invitation))).scalars()
        }
    assert remaining == {
        "fresh@example.com": "expired",
        "recent@example.com": "expired",
        "valid@example.com": "pending",
    }
