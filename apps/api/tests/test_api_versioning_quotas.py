"""Issue #22: API versioning header + key usage counting/quotas."""

import pytest

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers

# Pinned deliberately: the words an HTTP caller reads for a refused quota. The
# schema validator and the service guard both raise this, and the assertions
# below compare the 422 body against this literal, so neither copy can be
# reworded on its own.
QUOTA_MIN_MESSAGE = "usage quota must be at least 1 (omit it or send null for unlimited)"


def _quota_msg(resp) -> str:
    detail = resp.json()["detail"]
    assert isinstance(detail, list) and len(detail) == 1, resp.text
    # pydantic's own code, so only the wording differs from a plain ge=1 refusal.
    assert detail[0]["type"] == "greater_than_equal", resp.text
    return detail[0]["msg"]


async def test_api_version_header_on_api_responses(app_client):
    resp = await app_client.get("/")
    assert resp.status_code == 200
    assert resp.json()["api_version"] == "v1"

    owner = await register_user(app_client, "vera@example.com")
    await create_workspace(app_client, owner)
    resp = await app_client.get("/api/v1/workspaces", headers=auth_headers(owner))
    assert resp.headers.get("X-API-Version") == "v1"
    # non-API routes are not stamped
    assert "X-API-Version" not in (await app_client.get("/")).headers


async def test_key_usage_counted_and_visible(app_client):
    client = app_client
    owner = await register_user(client, "walt@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = (
        await client.post(
            "/api/v1/api-keys",
            json={"name": "metered", "permissions": ["member:read"]},
            headers=headers,
        )
    ).json()
    assert created["usage_count"] == 0
    assert created["usage_quota"] is None

    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    await client.get("/api/v1/members", headers=key_headers)
    await client.get("/api/v1/members", headers=key_headers)

    listed = (await client.get("/api/v1/api-keys", headers=headers)).json()
    item = next(k for k in listed if k["id"] == created["id"])
    assert item["usage_count"] == 2


async def test_key_quota_enforced(app_client):
    client = app_client
    owner = await register_user(client, "xena@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = (
        await client.post(
            "/api/v1/api-keys",
            json={"name": "capped", "permissions": ["member:read"], "usage_quota": 1},
            headers=headers,
        )
    ).json()
    assert created["usage_quota"] == 1

    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    first = await client.get("/api/v1/members", headers=key_headers)
    assert first.status_code == 200
    assert first.headers["X-API-Key-Quota"] == "1"
    assert first.headers["X-API-Key-Remaining"] == "0"

    # quota exhausted → 403 without touching usage further
    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()

    # raising the quota unblocks the key
    patched = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": 5},
        headers=headers,
    )
    assert patched.status_code == 200
    assert patched.json()["usage_quota"] == 5
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    # clearing the quota (None) means unlimited
    cleared = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": None},
        headers=headers,
    )
    assert cleared.json()["usage_quota"] is None


async def test_refused_quota_words_match_every_json_type(app_client):
    """A BeforeValidator reads the raw value, before pydantic coerces it to
    int, so int, float and str are all checked here. A client that sends "0"
    from a form or a YAML config gets the same refusal as one sending 0."""
    client = app_client
    owner = await register_user(client, "quota-types@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    async def mint(quota):
        return await client.post(
            "/api/v1/api-keys",
            json={"name": "typed", "permissions": [], "usage_quota": quota},
            headers=headers,
        )

    for quota in (0, -1, -99, 0.0, -1.0, "0", "-5"):
        resp = await mint(quota)
        assert resp.status_code == 422, (quota, resp.text)
        assert _quota_msg(resp) == QUOTA_MIN_MESSAGE, quota

    # null is unlimited, and a bool is not a quota count: pydantic coerces
    # true to 1, and false is refused above as 0.
    assert (await mint(None)).status_code == 201
    assert (await mint(True)).json()["usage_quota"] == 1

    # A value that is not a number is a type error, not a refused quota.
    for bad in ("many", "-inf", "inf", "nan"):
        resp = await mint(bad)
        assert resp.status_code == 422, (bad, resp.text)
    assert resp.json()["detail"][0]["type"] == "int_parsing", (bad, resp.text)

    # A fraction wants an integer, not a range check: 0.5 keeps main's answer.
    resp = await mint(0.5)
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["type"] == "int_from_float", resp.text


def test_huge_json_integer_reaches_pydantic():
    """A JSON integer is unbounded, so one wider than a float64 must not
    overflow out of the validator: OverflowError is not a pydantic error, so
    it would answer the request 500 with an empty body."""
    from src.schemas.api import ApiKeyCreate

    huge = 10**400
    assert ApiKeyCreate(name="huge", usage_quota=huge).usage_quota == huge


async def test_service_quota_guard_uses_the_same_words(app_client):
    """The schema is not the only check: seed and internal callers reach the
    service guard directly, and it carries the same message."""
    from src.db.session import SessionFactory
    from src.services.api_keys import ApiKeyError, ApiKeyService
    from src.services.auth import AuthService

    client = app_client
    owner = await register_user(client, "quota-svc@example.com")
    ws = await create_workspace(client, owner)

    async with SessionFactory() as session:
        service = ApiKeyService(session)
        user = await AuthService(session).get_by_email("quota-svc@example.com")
        with pytest.raises(ApiKeyError) as minted:
            await service.create_api_key(
                workspace_id=ws["id"],
                name="zero",
                permissions=[],
                actor=user,
                usage_quota=0,
            )
        assert str(minted.value) == QUOTA_MIN_MESSAGE

        key, _ = await service.create_api_key(
            workspace_id=ws["id"], name="capped", permissions=[], actor=user, usage_quota=5
        )
        with pytest.raises(ApiKeyError) as patched:
            await service.set_quota(ws["id"], key.id, 0, actor=user)
        assert str(patched.value) == QUOTA_MIN_MESSAGE


async def test_quota_patch_scoped_to_owner(app_client):
    client = app_client
    owner = await register_user(client, "willa@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post(
            "/api/v1/api-keys", json={"name": "mine", "permissions": []}, headers=headers
        )
    ).json()

    # an editor member of the same workspace still cannot touch another user's key
    roles = (await client.get("/api/v1/roles", headers=headers)).json()
    editor = next(r for r in roles if r["name"] == "editor")
    member = await register_user(client, "xara@example.com")
    invite = (
        await client.post(
            "/api/v1/invitations",
            json={"email": "xara@example.com", "role_id": editor["id"]},
            headers=headers,
        )
    ).json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member),
    )
    resp = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": 10},
        headers=ws_headers(member, ws["id"]),
    )
    assert resp.status_code == 404  # not leaked across users


async def test_quota_patch_validates_and_scopes_to_owner(app_client):
    client = app_client
    owner = await register_user(client, "yara@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    created = (
        await client.post(
            "/api/v1/api-keys", json={"name": "q", "permissions": []}, headers=headers
        )
    ).json()

    resp = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": -1},
        headers=headers,
    )
    assert resp.status_code == 422
    assert _quota_msg(resp) == QUOTA_MIN_MESSAGE

    stranger = await register_user(client, "zane@example.com")
    resp = await client.patch(
        f"/api/v1/api-keys/{created['id']}",
        json={"usage_quota": 10},
        headers=auth_headers(stranger),
    )
    assert resp.status_code in (400, 403)  # no workspace scope, no membership


async def test_zero_quota_is_rejected(app_client):
    """A quota of 0 is a key that can never authenticate: `usage_count <
    usage_quota` is `0 < 0`, so the first request is refused and every one
    after it. It is refused at the counter instead — no mint, no meter."""
    client = app_client
    owner = await register_user(client, "quinn@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "quota-zero", "permissions": ["member:read"], "usage_quota": 0},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    # The schema refuses the quota with the same words the service guard uses
    # for direct callers, so the two copies cannot drift into a third wording.
    assert _quota_msg(resp) == QUOTA_MIN_MESSAGE
    assert (await client.get("/api/v1/api-keys", headers=headers)).json() == []

    # A positive quota is still the way to bound a key.
    created = await client.post(
        "/api/v1/api-keys",
        json={"name": "metered", "permissions": ["member:read"], "usage_quota": 2},
        headers=headers,
    )
    assert created.status_code == 201, created.text

    # Patching an existing key to 0 would kill it the same way, so it is
    # refused there too — the key keeps the quota it had.
    resp = await client.patch(
        f"/api/v1/api-keys/{created.json()['id']}",
        json={"usage_quota": 0},
        headers=headers,
    )
    assert resp.status_code == 422, resp.text
    assert _quota_msg(resp) == QUOTA_MIN_MESSAGE
    keys = (await client.get("/api/v1/api-keys", headers=headers)).json()
    assert keys[0]["usage_quota"] == 2, keys

    # ... and it still authenticates.
    key_headers = {
        "Authorization": f"Bearer {created.json()['key']}",
        "X-Workspace-ID": ws["id"],
    }
    ok = await client.get("/api/v1/members", headers=key_headers)
    assert ok.status_code == 200, ok.text
    assert ok.headers["X-API-Key-Remaining"] == "1", ok.text
