import hashlib
from datetime import UTC, datetime

from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)


async def _create_key(client, headers, name="ci-deploy", permissions=None, body=None):
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "permissions": permissions or [], **(body or {})},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def test_owner_can_create_list_and_use_api_key(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers, permissions=["member:read", "role:read"])
    assert key["key"].startswith("sk_live_")
    assert key["key_prefix"] == key["key"][: len(key["key_prefix"])]
    assert key["permissions"] == ["member:read", "role:read"]
    assert key["revoked_at"] is None

    # never stored raw — only the hash lives in the DB
    from src.db.session import SessionFactory
    from src.models.api_key import ApiKey

    async with SessionFactory() as session:
        row = await session.get(ApiKey, key["id"])
        assert row.key_hash != key["key"]
        assert row.key_hash == hashlib.sha256(key["key"].encode()).hexdigest()

    # the key authenticates and can read members
    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}
    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 200

    # list shows the key metadata, never the secret
    keys = await client.get("/api/v1/api-keys", headers=headers)
    assert keys.status_code == 200
    item = next(k for k in keys.json() if k["id"] == key["id"])
    assert "key" not in item
    assert item["key_prefix"].startswith("sk_live_")
    assert item["last_used_at"] is not None  # touch() ran on the members call


async def test_api_key_timestamps_are_offset_aware(app_client):
    """Every timestamp in the payload carries its UTC offset.

    A naive ISO string makes `new Date(...)` parse as local time in the
    browser, so a key renders at a different wall clock than `Expires`.
    """
    client = app_client
    owner = await register_user(client, "tess@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(
        client,
        headers,
        permissions=["member:read"],
        body={"expires_at": "2027-01-01T00:00:00Z"},
    )
    # a real call so touch() populates last_used_at, then revoke
    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200
    resp = await client.delete(f"/api/v1/api-keys/{key['id']}", headers=headers)
    assert resp.status_code == 204

    listed = await client.get("/api/v1/api-keys", headers=headers)
    assert listed.status_code == 200
    item = next(k for k in listed.json() if k["id"] == key["id"])
    for field in ("created_at", "expires_at", "last_used_at", "revoked_at"):
        assert item[field] is not None, field
        stamp = datetime.fromisoformat(item[field])
        assert stamp.utcoffset() is not None, f"{field}: {item[field]}"


async def test_api_key_is_capped_by_owner_permissions(app_client):
    client = app_client
    owner = await register_user(client, "grace@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    # owner holds "*" → may mint a key with the full catalog
    from src.core.permissions import ALL_PERMISSIONS

    key = await _create_key(client, headers, permissions=ALL_PERMISSIONS)
    assert key["permissions"] == sorted(ALL_PERMISSIONS)


async def test_api_key_cannot_escalate_beyond_creator_permissions(app_client):
    client = app_client
    owner = await register_user(client, "lina@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    roles = await client.get("/api/v1/roles", headers=headers)
    editor = next(r for r in roles.json() if r["name"] == "editor")

    member = await register_user(client, "mina@example.com")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "mina@example.com", "role_id": editor["id"]},
        headers=headers,
    )
    invite = invite.json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member),
    )

    member_headers = ws_headers(member, ws["id"])

    # editor may grant exactly the permissions they hold
    key = await _create_key(
        client, member_headers, name="script", permissions=["member:read", "role:read"]
    )
    assert key["permissions"] == ["member:read", "role:read"]

    # ... but not anything beyond them
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "sneaky", "permissions": ["workspace:delete"]},
        headers=member_headers,
    )
    assert resp.status_code == 403
    assert "workspace:delete" in resp.json()["detail"]

    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "sneaky2", "permissions": ["member:read", "member:update"]},
        headers=member_headers,
    )
    assert resp.status_code == 403
    assert "member:update" in resp.json()["detail"]


async def test_api_key_enforces_its_own_permissions(app_client):
    client = app_client
    owner = await register_user(client, "nora@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    read_only = await _create_key(client, headers, name="read-only", permissions=["member:read"])
    key_headers = {"Authorization": f"Bearer {read_only['key']}", "X-Workspace-ID": ws["id"]}

    # allowed
    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 200

    # missing member:update → forbidden, even though the owner could do it
    resp = await client.patch(
        "/api/v1/members/00000000-0000-0000-0000-000000000000",
        json={"role_id": "00000000-0000-0000-0000-000000000000"},
        headers=key_headers,
    )
    assert resp.status_code == 403
    assert "member:update" in resp.json()["detail"]

    resp = await client.get("/api/v1/api-keys", headers=key_headers)
    assert resp.status_code == 403
    assert "apikey:read" in resp.json()["detail"]


async def test_api_key_scoped_to_its_workspace(app_client):
    client = app_client
    owner = await register_user(client, "ola@example.com")
    ws_a = await create_workspace(client, owner, name="Alpha")
    ws_b = await create_workspace(client, owner, name="Beta")
    key = await _create_key(client, ws_headers(owner, ws_a["id"]), permissions=["member:read"])

    # wrong workspace header → 403 (key is scoped to Alpha)
    resp = await client.get(
        "/api/v1/members",
        headers={"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws_b["id"]},
    )
    assert resp.status_code == 403


async def test_revoked_key_is_rejected(app_client):
    client = app_client
    owner = await register_user(client, "pia@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    key = await _create_key(client, headers, permissions=["member:read"])
    key_headers = {"Authorization": f"Bearer {key['key']}", "X-Workspace-ID": ws["id"]}

    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    resp = await client.delete(f"/api/v1/api-keys/{key['id']}", headers=headers)
    assert resp.status_code == 204

    # revoked → the key can no longer authenticate
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 401

    # listing marks it revoked
    keys = await client.get("/api/v1/api-keys", headers=headers)
    assert next(k for k in keys.json() if k["id"] == key["id"])["revoked_at"] is not None


async def test_api_key_management_requires_permissions(app_client):
    client = app_client
    owner = await register_user(client, "quinn@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    # a custom role without any apikey permissions may not manage keys at all
    resp = await client.post(
        "/api/v1/roles",
        json={
            "name": "no-keys",
            "description": "role without apikey access",
            "permissions": ["workspace:read"],
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    no_keys_role_id = resp.json()["id"]

    guest = await register_user(client, "rita@example.com")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "rita@example.com", "role_id": no_keys_role_id},
        headers=headers,
    )
    invite = invite.json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(guest),
    )

    guest_headers = ws_headers(guest, ws["id"])

    # a role without apikey:read cannot list API keys
    resp = await client.get("/api/v1/api-keys", headers=guest_headers)
    assert resp.status_code == 403

    # a role without apikey:create cannot create API keys
    resp = await client.post(
        "/api/v1/api-keys", json={"name": "nope", "permissions": []}, headers=guest_headers
    )
    assert resp.status_code == 403


async def test_viewer_can_manage_their_own_api_keys(app_client):
    """Every system role — including the weakest, viewer — may manage its own
    keys; creation stays capped by the creator's own permissions."""
    client = app_client
    owner = await register_user(client, "sven@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    roles = await client.get("/api/v1/roles", headers=headers)
    viewer_role = next(r for r in roles.json() if r["name"] == "viewer")

    guest = await register_user(client, "tora@example.com")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "tora@example.com", "role_id": viewer_role["id"]},
        headers=headers,
    )
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(guest),
    )
    guest_headers = ws_headers(guest, ws["id"])

    # starts with an empty personal list
    resp = await client.get("/api/v1/api-keys", headers=guest_headers)
    assert resp.status_code == 200
    assert resp.json() == []

    # may mint a key capped at viewer-level permissions
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "mine", "permissions": ["member:read"]},
        headers=guest_headers,
    )
    assert resp.status_code == 201, resp.text

    # and sees exactly that key afterwards
    resp = await client.get("/api/v1/api-keys", headers=guest_headers)
    assert [k["name"] for k in resp.json()] == ["mine"]


async def test_effective_permissions_matches_role(app_client):
    client = app_client
    owner = await register_user(client, "sita@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await client.get("/api/v1/api-keys/effective-permissions", headers=headers)
    assert resp.status_code == 200
    owner_perms = resp.json()["permissions"]
    assert "*" in owner_perms
    # Owners mint keys too: key-only scopes must be offerable here as well.
    assert "notification:read" in owner_perms
    assert "notification:update" in owner_perms

    roles = await client.get("/api/v1/roles", headers=headers)
    editor = next(r for r in roles.json() if r["name"] == "editor")
    member = await register_user(client, "tara@example.com")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "tara@example.com", "role_id": editor["id"]},
        headers=headers,
    )
    invite = invite.json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member),
    )

    resp = await client.get(
        "/api/v1/api-keys/effective-permissions", headers=ws_headers(member, ws["id"])
    )
    assert resp.status_code == 200
    perms = resp.json()["permissions"]
    assert "apikey:create" in perms
    assert "workspace:delete" not in perms
    # Key-only scopes are always offerable for keys, even though no role holds them.
    assert "notification:read" in perms
    assert "notification:update" in perms


async def test_list_requires_workspace_header(app_client):
    client = app_client
    owner = await register_user(client, "uma@example.com")
    await create_workspace(client, owner)
    resp = await client.get("/api/v1/api-keys", headers=auth_headers(owner))
    assert resp.status_code == 400


async def test_unsorted_list_defaults_to_created_at_desc(app_client):
    """No sort in the request must still yield a total order: created_at desc,
    id desc as tiebreaker. created_at is server_default=now() (second
    granularity on SQLite), so a burst of keys ties — the tiebreaker is what
    keeps the order total, and the tie is asserted so it cannot silently go."""
    client = app_client
    owner = await register_user(client, "wren@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    for i in range(5):
        await _create_key(client, headers, name=f"k{i}")

    resp = await client.get("/api/v1/api-keys", params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert len({k["created_at"] for k in rows}) < len(rows), "expected a created_at tie"

    expected = sorted(rows, key=lambda k: (k["created_at"], k["id"]), reverse=True)
    assert [k["id"] for k in rows] == [k["id"] for k in expected]


async def test_unsorted_paging_partitions_the_set(app_client):
    """With the default order, every row lands on exactly one page."""
    client = app_client
    owner = await register_user(client, "vera@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    for i in range(5):
        await _create_key(client, headers, name=f"k{i}")

    async def page(offset, limit):
        resp = await client.get(
            "/api/v1/api-keys",
            params={"offset": offset, "limit": limit},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    full = await page(0, 10)
    paged = [k for offset in (0, 2, 4) for k in await page(offset, 2)]
    assert [k["id"] for k in paged] == [k["id"] for k in full]


_TIE_IDS = [f"00000000-0000-4000-8000-00000000000{i}" for i in (1, 2, 3)]


async def _seed_created_tie(client, owner, workspace_id, keys):
    """Insert api keys sharing one explicit `created_at`, as (id, name) pairs
    given in insertion order.

    Arranged, not hoped for: the stamp is never `func.now()` (second
    granularity on SQLite) and the ids are supplied, so a test can insert a tie
    group in an order that disagrees with id order. Without the id
    tiebreaker the group then comes back as inserted, which is what makes the
    pre-fix result distinguishable from the post-fix one.
    """
    me = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    assert me.status_code == 200, me.text
    stamp = datetime(2026, 1, 1, tzinfo=UTC)
    rows = [
        ApiKey(
            id=i,
            workspace_id=workspace_id,
            created_by_user_id=me.json()["id"],
            name=name,
            key_prefix=f"sk_live_{n:04d}",
            key_hash=f"{i}-hash",
            permissions=[],
            created_at=stamp,
            updated_at=stamp,
        )
        for n, (i, name) in enumerate(keys)
    ]
    async with SessionFactory() as session:
        session.add_all(rows)
        await session.commit()


async def test_explicit_sort_overrides_the_default_order(app_client):
    """An explicit sort replaces the default order, and is itself total: the
    tied `created_at` group comes back ordered by id, in the direction asked
    for. Ids ascend in insertion order, so `order[]=desc` cannot come back
    right without the tiebreaker, and ascending already disagrees with the
    default `created_at DESC, id DESC`."""
    client = app_client
    owner = await register_user(client, "xena@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    await _seed_created_tie(
        client, owner, ws["id"], list(zip(_TIE_IDS, ["k0", "k1", "k2"], strict=True))
    )
    await _create_key(client, headers, name="newer")  # a stamp of its own

    for order, reverse in (("asc", False), ("desc", True)):
        resp = await client.get(
            "/api/v1/api-keys",
            params={"sort[]": "created_at", "order[]": order, "limit": 10},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        tied = [k for k in rows if k["id"] in _TIE_IDS]
        assert len({k["created_at"] for k in tied}) == 1, f"{order}: expected a created_at tie"
        expected = sorted(rows, key=lambda k: (k["created_at"], k["id"]), reverse=reverse)
        assert [k["id"] for k in rows] == [k["id"] for k in expected], order
        assert [k["id"] for k in tied] == sorted(_TIE_IDS, reverse=reverse), order


async def test_explicit_sort_paging_partitions_the_set(app_client):
    """`name` is a plain String(150) with no unique constraint, so an explicit
    name sort ties. The tie group is inserted back to front, and reading it one
    row per page must reproduce the unpaginated read: no row repeated, none
    skipped."""
    client = app_client
    owner = await register_user(client, "yuki@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    await _seed_created_tie(client, owner, ws["id"], [(i, "dup") for i in reversed(_TIE_IDS)])

    async def page(offset, limit):
        resp = await client.get(
            "/api/v1/api-keys",
            params={"sort[]": "name", "order[]": "asc", "offset": offset, "limit": limit},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    rows = await page(0, 10)
    assert len({k["name"] for k in rows}) < len(rows), "expected a name tie"
    assert [k["id"] for k in rows] == _TIE_IDS

    paged: list[str] = []
    for offset in range(len(rows)):
        chunk = await page(offset, 1)
        assert len(chunk) == 1, (offset, chunk)
        paged.extend(k["id"] for k in chunk)
    assert paged == [k["id"] for k in rows]


async def test_create_api_key_strips_padded_name(app_client):
    client = app_client
    owner = await register_user(client, "pad-key@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await client.post(
        "/api/v1/api-keys", json={"name": "  ci-deploy  ", "permissions": []}, headers=headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "ci-deploy"
    listed = await client.get("/api/v1/api-keys", headers=headers)
    assert next(k for k in listed.json() if k["id"] == resp.json()["id"])["name"] == "ci-deploy"

    blank = await client.post(
        "/api/v1/api-keys", json={"name": "   ", "permissions": []}, headers=headers
    )
    assert blank.status_code == 422


async def test_api_key_service_stores_trimmed_name(app_client):
    """The service trims without the schema — seed and internal callers never
    pass through `ApiKeyCreate`."""
    from src.db.session import SessionFactory
    from src.models.api_key import ApiKey
    from src.services.api_keys import ApiKeyService
    from src.services.auth import AuthService

    client = app_client
    owner = await register_user(client, "pad-key-svc@example.com")
    ws = await create_workspace(client, owner)

    async with SessionFactory() as session:
        user = await AuthService(session).get_by_email("pad-key-svc@example.com")
        key, _ = await ApiKeyService(session).create_api_key(
            workspace_id=ws["id"], name="  ci-deploy  ", permissions=["member:read"], actor=user
        )

    async with SessionFactory() as session:
        stored = await session.get(ApiKey, key.id)
        assert stored.name == "ci-deploy"
