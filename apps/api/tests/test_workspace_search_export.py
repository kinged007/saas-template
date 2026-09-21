import json

from tests.conftest import create_workspace, register_user, ws_headers


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
    """Viewer/editor roles lack jobs:view, so search must omit job definitions."""
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
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == []
    resp = await client.get("/api/v1/workspaces/search", params={"q": "%_%"}, headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json()["results"] == []


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


async def test_search_rejects_blank_and_non_member(app_client):
    client, h, ws, conv = await _setup(app_client)
    assert (
        await client.get("/api/v1/workspaces/search", params={"q": " "}, headers=h)
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
    resp = await client.get("/api/v1/workspaces/export", headers=h)
    assert resp.status_code == 200, resp.text
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
    ):
        assert key in bundle, key
    assert bundle["workspace"]["id"] == ws["id"]
    assert any(m["email"] == "searcher@example.com" for m in bundle["members"])
    # No secrets leak: key hashes, webhook secrets, job ciphertext stay out.
    assert not any("key_hash" in k or "secret" in str(k).lower() for k in bundle["api_keys"])
    assert not any("secret" in str(s).lower() for s in bundle["webhook_subscriptions"])

    csv_resp = await client.get(
        "/api/v1/workspaces/export", params={"format": "csv", "resource": "members"}, headers=h
    )
    assert csv_resp.status_code == 200, csv_resp.text
    assert csv_resp.headers["content-type"].startswith("text/csv")
    assert csv_resp.text.splitlines()[0] == "email,display_name,role,status,joined_at"
    bad = await client.get(
        "/api/v1/workspaces/export",
        params={"format": "csv", "resource": "nope"},
        headers=h,
    )
    assert bad.status_code == 422


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
