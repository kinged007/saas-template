import asyncio
import csv
import io
import json

from tests.conftest import create_workspace, register_user, ws_headers


async def _wait_for_audit_export(client, headers, params=None, tries: int = 150):
    """Re-read the export until the bus has committed `workspace.created`.

    Audit rows are written by a background event-bus task, so a request issued
    right after setup can be served before they land. The last read is returned
    either way, so a genuine failure still shows the export body.
    """
    for _ in range(tries):
        resp = await client.get("/api/v1/workspaces/export", params=params, headers=headers)
        assert resp.status_code == 200, resp.text
        if "workspace.created" in resp.text:
            break
        await asyncio.sleep(0.02)
    return resp


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
    resp = await _wait_for_audit_export(client, h)
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
    from sqlalchemy import delete, select

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


async def test_export_audit_csv(app_client):
    """The audit log is selectable in the export card and exports as CSV."""
    from src.services.search_export import CSV_RESOURCES

    client, h, ws, conv = await _setup(app_client)
    resp = await _wait_for_audit_export(client, h, params={"format": "csv", "resource": "audit"})
    assert resp.headers["content-type"].startswith("text/csv")
    assert "attachment" in resp.headers["content-disposition"]
    assert (
        resp.text.splitlines()[0]
        == "created_at,actor_email,action,resource_type,resource_id,ip_address"
    )
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


async def test_export_resources_endpoint_is_the_selector_source(app_client):
    """The frontend selector reads this list, so it must match CSV_RESOURCES."""
    from src.services.search_export import CSV_RESOURCES

    client, h, ws, conv = await _setup(app_client)
    resp = await client.get("/api/v1/workspaces/export/resources", headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["resources"] == list(CSV_RESOURCES)
    assert "audit" in resp.json()["resources"]


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
