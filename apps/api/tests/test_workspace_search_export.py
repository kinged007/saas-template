import asyncio
import csv
import io
import json
from uuid import uuid4

import pytest
from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry
from tests.conftest import create_workspace, register_user, ws_headers


async def _wait_for_audit_export(
    client, headers, workspace_id, params=None, timeout_secs: float = 5.0, interval: float = 0.02
):
    """Return the export, requested once the bus has committed `workspace.created`.

    Audit rows are written by a background event-bus task, so an export issued
    right after setup can be served before they land. The gate polls the audit
    table instead of re-reading the export: every export call publishes its own
    `workspace.exported` audit event, so retrying the export would add work to
    the bus this waits on. One export is issued, after the gate.
    """
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_secs
    while True:
        async with SessionFactory() as session:
            result = await session.execute(
                select(AuditLogEntry.action).where(AuditLogEntry.workspace_id == workspace_id)
            )
            landed = "workspace.created" in set(result.scalars().all())
        if landed or loop.time() >= deadline:
            break
        await asyncio.sleep(interval)
    assert landed, f"event bus did not commit workspace.created within {timeout_secs}s"
    resp = await client.get("/api/v1/workspaces/export", params=params, headers=headers)
    assert resp.status_code == 200, resp.text
    return resp


async def test_wait_for_audit_export_gives_up_without_issuing_export(app_client, monkeypatch):
    """The exhausted gate: no `workspace.created` row -> no export, only the assert."""
    from src.services.search_export import SearchExportService

    issued = []

    async def _recording_export_json(self, **kwargs):
        issued.append(kwargs)
        return {}

    monkeypatch.setattr(SearchExportService, "export_json", _recording_export_json)

    # Real credentials, so the export is reachable and the counter below is
    # evidence rather than a 401 short-circuit.
    tokens = await register_user(app_client, "gate@example.com")
    ws = await create_workspace(app_client, tokens, name="Gate Co")
    # The gate watches a workspace id the bus has never seen, so the row can never land.
    missing_workspace_id = str(uuid4())
    timeout_secs, interval = 0.05, 0.01
    with pytest.raises(AssertionError, match="event bus did not commit workspace.created"):
        await _wait_for_audit_export(
            app_client,
            ws_headers(tokens, ws["id"]),
            missing_workspace_id,
            timeout_secs=timeout_secs,
            interval=interval,
        )
    assert issued == [], "the gate must abort before the export is issued"


async def _me_id(client, tokens):
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _setup(app_client):
    client = app_client
    tokens = await register_user(client, "searcher@example.com")
    ws = await create_workspace(client, tokens, name="Search Co")
    h = ws_headers(tokens, ws["id"])
    # Seed searchable content: conversation + invitation.
    roles = (await client.get("/api/v1/roles", headers=h)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    other_tokens = await register_user(client, "teammate@example.com")
    from tests.conftest import auth_headers as _ah

    other_id = await _me_id(client, other_tokens)
    invite_tm = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "teammate@example.com", "role_id": viewer["id"]},
            headers=h,
        )
    ).json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite_tm["token"]},
        headers=_ah(other_tokens),
    )
    conv_resp = await client.post(
        "/api/v1/conversations",
        json={
            "title": "Quarterly planning",
            "participant_user_ids": [other_id],
            "initial_message": "Discuss the zebra migration timeline",
        },
        headers=h,
    )
    assert conv_resp.status_code == 201, conv_resp.text
    conv = conv_resp.json()
    await client.post(
        "/api/v1/invitations",
        json={"email": "newhire@example.com", "role_id": viewer["id"]},
        headers=h,
    )
    return client, h, ws, conv


async def test_search_finds_workspace_content(app_client):
    client, h, ws, conv = await _setup(app_client)
    resp = await client.get("/api/v1/workspaces/search", params={"q": "zebra"}, headers=h)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["query"] == "zebra"
    types = {r["type"] for r in body["results"]}
    assert {"conversation", "message"} <= types
    assert all("id" in r and "title" in r for r in body["results"])


async def test_search_scoped_to_active_workspace(app_client):
    client, h, ws, conv = await _setup(app_client)
    tokens2 = await register_user(client, "other-ws@example.com")
    ws2 = await create_workspace(client, tokens2, name="Other Co")
    h2 = ws_headers(tokens2, ws2["id"])
    resp = await client.get("/api/v1/workspaces/search", params={"q": "zebra"}, headers=h2)
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == []


async def test_search_restricted_to_participant_conversations(app_client):
    """A member who is not a participant must not see others' conversations/messages."""
    client, h, ws, conv = await _setup(app_client)
    third_tokens = await register_user(client, "third@example.com")
    from tests.conftest import auth_headers as _ah2

    roles = (await client.get("/api/v1/roles", headers=h)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "third@example.com", "role_id": viewer["id"]},
            headers=h,
        )
    ).json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=_ah2(third_tokens),
    )
    h3 = ws_headers(third_tokens, ws["id"])
    resp = await client.get("/api/v1/workspaces/search", params={"q": "zebra"}, headers=h3)
    assert resp.status_code == 200, resp.text
    leaked = [r for r in resp.json()["results"] if r["type"] in ("conversation", "message")]
    assert leaked == []


async def test_search_hides_jobs_without_jobs_view(app_client):
    """Viewer/editor roles lack jobs:read, so search must omit job definitions."""
    client, h, ws, conv = await _setup(app_client)
    roles = (await client.get("/api/v1/roles", headers=h)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    viewer_tokens = await register_user(client, "jobs-viewer@example.com")
    from tests.conftest import auth_headers as _ah_jobs

    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "jobs-viewer@example.com", "role_id": viewer["id"]},
            headers=h,
        )
    ).json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=_ah_jobs(viewer_tokens),
    )
    from tests.conftest import ws_headers as _wh_jobs

    h_viewer = _wh_jobs(viewer_tokens, ws["id"])
    resp = await client.get("/api/v1/workspaces/search", params={"q": "echo"}, headers=h_viewer)
    assert resp.status_code == 200, resp.text
    assert [r for r in resp.json()["results"] if r["type"] == "job"] == []
    owner_resp = await client.get(
        "/api/v1/workspaces/search", params={"q": "expire stale invitations"}, headers=h
    )
    assert owner_resp.status_code == 200, owner_resp.text
    assert any(r["type"] == "job" for r in owner_resp.json()["results"])


async def test_search_escapes_like_wildcards(app_client):
    # "%_%" matches every row as wildcards; literally it appears nowhere.
    client, h, ws, conv = await _setup(app_client)
    resp = await client.get("/api/v1/workspaces/search", params={"q": "%"}, headers=h)
    assert resp.status_code == 422, resp.text
    resp = await client.get("/api/v1/workspaces/search", params={"q": "%_%"}, headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == []


async def test_conversation_list_escapes_like_wildcards(app_client):
    # "%" appears in no title; unescaped it would match every conversation.
    client, h, ws, conv = await _setup(app_client)
    resp = await client.get("/api/v1/conversations", params={"q": "%"}, headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


async def test_export_strips_superuser_and_rejects_bad_format(app_client):
    client, h, ws, conv = await _setup(app_client)
    resp = await client.get("/api/v1/workspaces/export", headers=h)
    assert resp.status_code == 200, resp.text
    bundle = json.loads(resp.text)
    assert not any("is_superuser" in m for m in bundle["members"])
    assert bundle.get("truncated") is False
    bad = await client.get("/api/v1/workspaces/export", params={"format": "xml"}, headers=h)
    assert bad.status_code == 422
    csv_resp = await client.get(
        "/api/v1/workspaces/export",
        params={"format": "csv", "resource": "jobs"},
        headers=h,
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.text.splitlines()[0] == "key,name,enabled,cron_schedule,next_run_at"


async def test_search_rejects_blank_and_short_and_non_member(app_client):
    client, h, ws, conv = await _setup(app_client)
    assert (
        await client.get("/api/v1/workspaces/search", params={"q": " "}, headers=h)
    ).status_code == 422
    assert (
        await client.get("/api/v1/workspaces/search", params={"q": "z"}, headers=h)
    ).status_code == 422
    outsider = await register_user(client, "outsider@example.com")
    from tests.conftest import auth_headers

    resp = await client.get(
        "/api/v1/workspaces/search",
        params={"q": "zebra"},
        headers={**auth_headers(outsider), "X-Workspace-ID": ws["id"]},
    )
    assert resp.status_code == 403


async def test_export_json_and_csv(app_client):
    client, h, ws, conv = await _setup(app_client)
    resp = await _wait_for_audit_export(client, h, ws["id"])
    assert "attachment" in resp.headers["content-disposition"]
    bundle = json.loads(resp.text)
    for key in (
        "workspace",
        "members",
        "roles",
        "invitations",
        "api_keys",
        "jobs",
        "conversations",
        "messages",
        "notifications",
        "webhook_subscriptions",
        "audit",
    ):
        assert key in bundle, key
    assert bundle["workspace"]["id"] == ws["id"]
    assert any(m["email"] == "searcher@example.com" for m in bundle["members"])
    # Every member carries a profile key even when the user has no profile row,
    # so importers see one uniform member shape.
    assert all("profile" in m for m in bundle["members"])
    audit = bundle["audit"]
    assert audit, "expected audit rows in the bundle"
    for key in ("id", "actor_email", "action", "resource_type", "resource_id", "created_at"):
        assert key in audit[0], key
    assert any(
        a["action"] == "workspace.created"
        and a["actor_email"] == "searcher@example.com"
        and a["resource_id"] == ws["id"]
        for a in audit
    )
    # No secrets leak: key hashes, webhook secrets, job ciphertext stay out.
    assert not any("key_hash" in k or "secret" in str(k).lower() for k in bundle["api_keys"])
    assert not any("secret" in str(s).lower() for s in bundle["webhook_subscriptions"])

    csv_resp = await client.get(
        "/api/v1/workspaces/export", params={"format": "csv", "resource": "members"}, headers=h
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    member_rows = list(csv.DictReader(io.StringIO(csv_resp.text)))
    assert member_rows, "expected member rows"
    from src.services.search_export import CSV_RESOURCES

    assert list(member_rows[0]) == CSV_RESOURCES["members"]
    searcher = next(r for r in member_rows if r["email"] == "searcher@example.com")
    # The profile table must be exported, not just the user row: the seeded
    # member's name lives only in user_profiles, and issue #167 asks for those
    # fields "even if empty".
    assert searcher["profile_first_name"] == "Test"
    assert searcher["profile_last_name"] == "User"
    # Unset profile fields are empty cells, not dropped columns.
    assert searcher["profile_bio"] == ""
    assert searcher["profile_timezone"] == ""
    # Redacted by the public projection, so they stay out of the column set
    # rather than shipping as permanently empty.
    assert "profile_phone_number" not in searcher
    assert "profile_date_of_birth" not in searcher
    # structured profile values stay valid JSON, not Python repr
    assert json.loads(searcher["profile_custom_data"]) == {}
    bad = await client.get(
        "/api/v1/workspaces/export",
        params={"format": "csv", "resource": "nope"},
        headers=h,
    )
    assert bad.status_code == 422


async def test_export_members_csv_keeps_columns_for_members_without_profile(app_client):
    """A member with no profile row still gets every profile column, empty."""
    from src.services.search_export import CSV_RESOURCES

    client, h, ws, conv = await _setup(app_client)
    # register_user always creates a profile, so delete the row to get a member
    # without one — the columns must survive the missing row, not vanish with it.
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.user_profile import UserProfile
    from src.models.workspace import User

    email = "teammate@example.com"
    async with SessionFactory() as session:
        user_id = (
            (await session.execute(select(User).where(User.email == email).limit(1)))
            .scalar_one()
            .id
        )
        await session.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
        await session.commit()
        assert await session.get(UserProfile, user_id) is None

    resp = await client.get(
        "/api/v1/workspaces/export", params={"format": "csv", "resource": "members"}, headers=h
    )
    assert resp.status_code == 200, resp.text
    rows = {r["email"]: r for r in csv.DictReader(io.StringIO(resp.text))}
    assert email in rows
    bare = rows[email]
    assert set(bare) == set(CSV_RESOURCES["members"])
    for col in CSV_RESOURCES["members"]:
        if col.startswith("profile_"):
            assert bare[col] == "", col
    # The rest of the row is unaffected by the missing profile.
    assert bare["email"] == email
    assert bare["role"]


async def test_export_audit_details_drop_the_internal_source_event_id(app_client):
    """The export is a downloadable artifact, so it strips the dedupe key."""
    client, h, ws, conv = await _setup(app_client)
    await _wait_for_audit_export(client, h, ws["id"])
    async with SessionFactory() as session:
        session.add(
            AuditLogEntry(
                workspace_id=ws["id"],
                resource_type="workspace",
                resource_id=ws["id"],
                action="workspace.renamed",
                details={"source_event_id": "evt-1", "name": "Renamed"},
            )
        )
        await session.commit()

    bundle = json.loads((await client.get("/api/v1/workspaces/export", headers=h)).text)
    row = next(a for a in bundle["audit"] if a["action"] == "workspace.renamed")
    assert row["details"] == {"name": "Renamed"}


async def test_export_audit_csv(app_client):
    """The audit log is selectable in the export card and exports as CSV."""
    from src.services.search_export import CSV_RESOURCES

    client, h, ws, conv = await _setup(app_client)
    resp = await _wait_for_audit_export(
        client, h, ws["id"], params={"format": "csv", "resource": "audit"}
    )
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    expected = "id,created_at,actor_email,action,resource_type,resource_id,ip_address"
    assert resp.text.splitlines()[0] == expected
    rows = list(csv.DictReader(io.StringIO(resp.text)))
    assert rows, "expected audit rows"
    # Every row carries the full column set; unset values are empty, not dropped.
    assert all(set(r) == set(CSV_RESOURCES["audit"]) for r in rows)
    # `workspace.created` is written exactly once, so it is the one row that is
    # stable across the two separate export calls the suite makes. Later entries
    # (message.created, and the export's own workspace.exported) land
    # asynchronously and vary run to run.
    created = [r for r in rows if r["action"] == "workspace.created"]
    assert len(created) == 1, created
    assert created[0]["actor_email"] == "searcher@example.com"
    assert created[0]["resource_type"] == "workspace"
    assert created[0]["resource_id"] == ws["id"]
    assert created[0]["created_at"]
    # The id column round-trips, so a single row traces back to its own entry.
    json_entries = (await client.get("/api/v1/workspaces/export", headers=h)).json()["audit"]
    assert created[0]["id"]
    assert created[0]["id"] in {e["id"] for e in json_entries}


def test_export_csv_sanitises_formula_cells_for_every_resource():
    """A cell starting with = + - @ or a control character must not execute.

    Covers every resource in one place: export_csv is the only writer of
    tabular output, so a bug in the choke point reaches all of them.
    """
    from src.services.search_export import SearchExportService

    injections = {
        "members": {"email": "=cmd|' /C calc'!A0", "display_name": "+1+1", "avatar_url": None},
        "invitations": {"email": "@SUM(1+1)"},
        "api_keys": {"name": "-1+1", "key_prefix": None, "permissions": ["=evil"]},
        "jobs": {"key": "=1", "name": "@x"},
        "conversations": {"title": "-cmd", "last_message_preview": None},
        "notifications": {"title": "=1", "type": None},
        "audit": {"actor_email": "+1", "id": "=1"},
    }
    for resource, payload in injections.items():
        text = SearchExportService.export_csv({resource: [payload]}, resource)
        row = next(csv.DictReader(io.StringIO(text)))
        for key, value in payload.items():
            if value is None:
                continue
            cell = row[key]
            # Structured values stay valid JSON; only the leading formula
            # character is prefixed, so the original text is still recoverable.
            raw = value if isinstance(value, str) else json.dumps(value)
            if isinstance(value, list):
                raw = ";".join(value)
            assert cell == f"'{raw}", (resource, key, cell)

    # Excel discards a leading control character and evaluates what follows, so
    # a tab, CR or LF in front of a formula is the same payload.
    for control in ("\t", "\r", "\n"):
        payload = f"{control}=1+1"
        text = SearchExportService.export_csv({"members": [{"display_name": payload}]}, "members")
        assert next(csv.DictReader(io.StringIO(text)))["display_name"] == f"'{payload}", control


def test_export_csv_leaves_safe_values_untouched():
    """Sanitising must not rewrite ordinary cells, non-strings, or empty ones."""
    from src.services.search_export import SearchExportService

    payload = {
        "id": "abc-123",
        "email": "person@example.com",
        "display_name": "Ada Lovelace",
        "email_verified": True,
        "avatar_url": None,
    }
    text = SearchExportService.export_csv({"members": [payload]}, "members")
    row = next(csv.DictReader(io.StringIO(text)))
    assert row["id"] == "abc-123"
    assert row["email"] == "person@example.com"
    assert row["display_name"] == "Ada Lovelace"
    assert row["email_verified"] == "True"
    assert row["avatar_url"] == ""


async def test_export_members_csv_neutralises_injected_display_name(app_client):
    """End to end: a formula-shaped display_name is prefixed in the response."""
    from src.db.session import SessionFactory
    from src.models.workspace import User

    client, h, ws, conv = await _setup(app_client)
    payload = "=cmd|' /C calc'!A0"
    async with SessionFactory() as session:
        user_id = (
            (
                await session.execute(
                    select(User).where(User.email == "teammate@example.com").limit(1)
                )
            )
            .scalar_one()
            .id
        )
        user = await session.get(User, user_id)
        user.display_name = payload
        await session.commit()

    resp = await client.get(
        "/api/v1/workspaces/export", params={"format": "csv", "resource": "members"}, headers=h
    )
    assert resp.status_code == 200, resp.text
    rows = {r["email"]: r for r in csv.DictReader(io.StringIO(resp.text))}
    assert rows["teammate@example.com"]["display_name"] == f"'{payload}"
    # The same value is untouched in the JSON export, which is not a
    # spreadsheet: only the CSV is defused.
    json_rows = (await client.get("/api/v1/workspaces/export", headers=h)).json()["members"]
    assert any(m["display_name"] == payload for m in json_rows)


async def test_export_resources_endpoint_is_the_selector_source(app_client):
    """The frontend selector reads this list, so it must match CSV_RESOURCES."""
    from src.services.search_export import CSV_RESOURCES

    client, h, ws, conv = await _setup(app_client)
    resp = await client.get("/api/v1/workspaces/export/resources", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["resources"] == list(CSV_RESOURCES)
    assert "audit" in resp.json()["resources"]


async def test_search_export_permission_check_ignores_suspended_member(app_client):
    """#300: `_can` decides whether job rows reach the caller, so a suspended
    member's row must not count as a membership there."""
    from src.core.permissions import JOB_READ
    from src.db.session import SessionFactory
    from src.services.search_export import SearchExportService
    from tests.conftest import auth_headers

    client = app_client
    owner = await register_user(client, "can-owner@example.com")
    ws = await create_workspace(client, owner, name="Can Co")
    h = ws_headers(owner, ws["id"])
    admin_role = next(
        r for r in (await client.get("/api/v1/roles", headers=h)).json() if r["name"] == "admin"
    )
    admin_tokens = await register_user(client, "can-admin@example.com")
    admin_invite = await client.post(
        "/api/v1/invitations",
        json={"email": "can-admin@example.com", "role_id": admin_role["id"]},
        headers=h,
    )
    assert admin_invite.status_code == 201, admin_invite.text
    joined = await client.post(
        "/api/v1/invitations/accept",
        params={"token": admin_invite.json()["token"]},
        headers=auth_headers(admin_tokens),
    )
    assert joined.status_code == 200, joined.text
    admin_id = await _me_id(client, admin_tokens)
    member_id = next(
        m
        for m in (await client.get("/api/v1/members", headers=h)).json()
        if m["email"] == "can-admin@example.com"
    )["membership_id"]

    async with SessionFactory() as session:
        service = SearchExportService(session)
        assert await service._can(ws["id"], admin_id, JOB_READ) is True

    suspended = await client.post(f"/api/v1/members/{member_id}/suspend", headers=h)
    assert suspended.status_code == 200, suspended.text

    async with SessionFactory() as session:
        service = SearchExportService(session)
        assert await service._can(ws["id"], admin_id, JOB_READ) is False


async def test_export_requires_audit_read(app_client):
    """Viewers (workspace:read only) can search but cannot export the full dump."""
    client, h, ws, conv = await _setup(app_client)
    roles = (await client.get("/api/v1/roles", headers=h)).json()
    viewer = next(r for r in roles if r["name"] == "viewer")
    viewer_tokens = await register_user(client, "export-viewer@example.com")
    from tests.conftest import auth_headers as _ah3

    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "export-viewer@example.com", "role_id": viewer["id"]},
            headers=h,
        )
    ).json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=_ah3(viewer_tokens),
    )
    from tests.conftest import ws_headers as _wh

    h_viewer = _wh(viewer_tokens, ws["id"])
    # Search still works for viewers.
    search = await client.get("/api/v1/workspaces/search", params={"q": "zebra"}, headers=h_viewer)
    assert search.status_code == 200, search.text
    # Export is gated on audit:read (owner/admin), not workspace:read.
    export = await client.get("/api/v1/workspaces/export", headers=h_viewer)
    assert export.status_code == 403, export.text
    # Owner keeps export access.
    owner_export = await client.get("/api/v1/workspaces/export", headers=h)
    assert owner_export.status_code == 200, owner_export.text
