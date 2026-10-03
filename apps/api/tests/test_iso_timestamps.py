"""Every datetime the API serializes for a client carries a UTC offset (#489).

A naive ISO string makes `new Date(...)` parse as local time in the browser, so a
row renders at a different wall clock than the instant the server stored.
"""

from __future__ import annotations

import ast
import asyncio
import csv
import io
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from src.core.dates import iso_or_none
from src.db.session import SessionFactory
from src.events.subjects import Subjects
from src.jobs.registry import JobSpec, job_registry
from src.models.core import Notification
from src.models.webhook import WebhookDelivery
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)

SRC = Path(__file__).resolve().parents[1] / "src"

ISO_PREFIX = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d")
ISO_OFFSET = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$")

# A receiver is fine when it already carries an offset. `p.date_of_birth` is a
# `Date` column with none to give, and `key.expires_at` is the apikey.created
# payload, which the open PR #561 serializes on its own.
OK_CALL = re.compile(r"^(?:ensure_utc\(|now_utc\(|datetime\.now\(UTC\))")
OK_FIELD = {"p.date_of_birth", "key.expires_at"}


def assert_offset_aware(payload, where="$") -> None:
    """Fail on any ISO timestamp string in `payload` that carries no offset."""
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert_offset_aware(value, f"{where}.{key}")
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            assert_offset_aware(value, f"{where}[{index}]")
    elif isinstance(payload, str) and ISO_PREFIX.match(payload):
        assert ISO_OFFSET.match(payload), f"{where} has no UTC offset: {payload}"


# --------------------------------------------------------------------- the helper


def test_iso_or_none_attaches_utc_to_a_naive_value():
    assert iso_or_none(datetime(2027, 1, 1)) == "2027-01-01T00:00:00+00:00"


def test_iso_or_none_normalizes_an_aware_value_to_utc():
    assert iso_or_none(datetime(2027, 1, 1, 9, tzinfo=timezone(timedelta(hours=9)))) == (
        "2027-01-01T00:00:00+00:00"
    )


def test_iso_or_none_passes_none_through():
    assert iso_or_none(None) is None


# --------------------------------------------------------------------- the guard


def test_no_bare_isoformat_on_a_datetime_remains():
    """A `grep` count drifts as other PRs land; this fails the moment one is added."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                not isinstance(node, ast.Call)
                or not isinstance(node.func, ast.Attribute)
                or node.func.attr != "isoformat"
            ):
                continue
            receiver = ast.unparse(node.func.value)
            if OK_CALL.match(receiver) or receiver in OK_FIELD:
                continue
            offenders.append(f"{path.relative_to(SRC)}:{node.lineno} {receiver}")
    assert offenders == []


# --------------------------------------------------------------------- HTTP level


@job_registry.register(
    JobSpec(
        key="iso.probe",
        name="Offset probe (test)",
        description="Does nothing, so a run and its logs exist to serialize.",
        scope="workspace",
        schedule="0 5 * * *",
        params_schema={},
        default_enabled=False,
        missed_policy="single",
        timeout_seconds=30,
    )
)
async def _probe(ctx) -> None:
    return None


async def _owner_workspace(client, email: str):
    """Owner tokens, their workspace, and workspace-scoped headers."""
    owner = await register_user(client, email)
    ws = await create_workspace(client, owner, name=f"WS {email.split('@')[0]}")
    return owner, ws, ws_headers(owner, ws["id"])


async def _joined_member(client, owner, ws, email: str) -> dict:
    """Invite `email`, register it, accept: the user id a conversation needs."""
    headers = ws_headers(owner, ws["id"])
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": viewer["id"]},
        headers=headers,
    )
    assert invite.status_code == 201, invite.text
    tokens = await register_user(client, email)
    accepted = await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(tokens),
    )
    assert accepted.status_code == 200, accepted.text
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    return me.json()


async def _assert_endpoint(client, method, url, headers, body=None) -> dict:
    resp = await client.request(method, url, json=body, headers=headers)
    assert resp.status_code == 200, (url, resp.text)
    assert_offset_aware(resp.json(), url)
    return resp.json()


async def test_workspace_families_carry_an_offset(app_client):
    """Workspaces, members, roles, invitations, notifications, profile, admin, audit."""
    client = app_client
    owner, ws, headers = await _owner_workspace(client, "root@example.com")  # SUPERADMIN_EMAIL
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    invited = await client.post(
        "/api/v1/invitations",
        json={"email": "new@example.com", "role_id": viewer["id"]},
        headers=headers,
    )
    assert invited.status_code == 201, invited.text

    # notification_to_dict only runs when a notification row exists
    me = (await client.get("/api/v1/auth/me", headers=auth_headers(owner))).json()
    async with SessionFactory() as session:
        session.add(
            Notification(
                user_id=me["id"],
                workspace_id=ws["id"],
                type="workspace_invitation",
                title="Probe",
                payload={},
            )
        )
        await session.commit()

    for url in (
        "/api/v1/workspaces",
        f"/api/v1/workspaces/{ws['id']}",
        "/api/v1/members",
        "/api/v1/roles",
        "/api/v1/invitations",
        "/api/v1/notifications",
        "/api/v1/me/profile",
        "/api/v1/audit",
        "/api/v1/admin/users",
        "/api/v1/admin/workspaces",
        "/api/v1/admin/audit",
    ):
        await _assert_endpoint(client, "get", url, headers)


async def test_conversation_families_carry_an_offset(app_client):
    client = app_client
    owner, ws, headers = await _owner_workspace(client, "iso-conv@example.com")
    other = await _joined_member(client, owner, ws, "iso-peer@example.com")
    conv = await client.post(
        "/api/v1/conversations",
        json={
            "title": "Kickoff",
            "participant_user_ids": [other["id"]],
            "initial_message": "hello",
        },
        headers=headers,
    )
    assert conv.status_code == 201, conv.text
    conv_id = conv.json()["id"]

    await _assert_endpoint(client, "get", "/api/v1/conversations", headers)
    await _assert_endpoint(client, "get", f"/api/v1/conversations/{conv_id}", headers)
    await _assert_endpoint(client, "get", f"/api/v1/conversations/{conv_id}/messages", headers)
    await _assert_endpoint(client, "patch", f"/api/v1/conversations/{conv_id}/read", headers, {})
    await _assert_endpoint(client, "patch", f"/api/v1/conversations/{conv_id}/unread", headers, {})
    await _assert_endpoint(
        client,
        "patch",
        f"/api/v1/conversations/{conv_id}/archive",
        headers,
        {"archived": True},
    )


async def test_job_and_webhook_families_carry_an_offset(app_client):
    client = app_client
    _, ws, headers = await _owner_workspace(client, "root@example.com")  # SUPERADMIN_EMAIL

    # definitions are provisioned by the workspaces.created workflow
    jobs = []
    for _ in range(50):
        jobs = (await client.get("/api/v1/jobs", headers=headers)).json()
        if any(j["key"] == "iso.probe" for j in jobs):
            break
        await asyncio.sleep(0.1)
    job = next(j for j in jobs if j["key"] == "iso.probe")

    started = await client.post(f"/api/v1/jobs/{job['id']}/execute", json={}, headers=headers)
    assert started.status_code == 201, started.text
    run_id = started.json()["id"]
    for _ in range(100):
        run = (await client.get(f"/api/v1/jobs/runs/{run_id}", headers=headers)).json()
        if run["status"] in ("success", "failed", "timed_out"):
            break
        await asyncio.sleep(0.05)

    subscription = await client.post(
        "/api/v1/webhooks/subscriptions",
        json={"url": "https://example.com/hook", "events": ["member.joined"]},
        headers=headers,
    )
    assert subscription.status_code == 201, subscription.text
    async with SessionFactory() as session:
        session.add(
            WebhookDelivery(
                subscription_id=subscription.json()["id"],
                workspace_id=ws["id"],
                event_type="member.joined",
                subject=Subjects.WORKSPACE_MEMBER_JOINED,
                payload={"event": "member.joined"},
                next_retry_at=datetime.now(UTC),
                last_attempt_at=datetime.now(UTC),
            )
        )
        await session.commit()

    for url in (
        "/api/v1/jobs",
        f"/api/v1/jobs/{job['id']}",
        f"/api/v1/jobs/{job['id']}/runs",
        "/api/v1/jobs/global",
        f"/api/v1/jobs/runs/{run_id}",
        f"/api/v1/jobs/runs/{run_id}/logs",
        "/api/v1/webhooks/subscriptions",
        "/api/v1/webhooks/deliveries",
    ):
        await _assert_endpoint(client, "get", url, headers)


async def test_export_json_and_csv_carry_an_offset(app_client):
    """CSV has no offset column, so the cell itself has to name the offset."""
    client = app_client
    _, ws, headers = await _owner_workspace(client, "iso-export@example.com")
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    assert (
        await client.post(
            "/api/v1/invitations",
            json={"email": "csv@example.com", "role_id": viewer["id"]},
            headers=headers,
        )
    ).status_code == 201

    await _assert_endpoint(client, "get", "/api/v1/workspaces/export", headers)

    resources = (await client.get("/api/v1/workspaces/export/resources", headers=headers)).json()[
        "resources"
    ]
    for resource in resources:
        resp = await client.get(
            "/api/v1/workspaces/export",
            params={"format": "csv", "resource": resource},
            headers=headers,
        )
        assert resp.status_code == 200, (resource, resp.text)
        for row in csv.DictReader(io.StringIO(resp.text)):
            assert_offset_aware(row, f"export.csv:{resource}")
