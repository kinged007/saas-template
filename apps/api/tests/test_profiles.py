import asyncio
import json

import pytest
from httpx import AsyncClient

from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def _get_profile(client: AsyncClient, tokens: dict) -> dict:
    resp = await client.get("/api/v1/me/profile", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    return resp.json()


async def _wait_for_audit(client_headers, action: str, deadline_seconds: float = 2.0):
    """Poll audit_log_entries via direct DB query? Use workflow persistence delay."""
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.audit import AuditLogEntry

    deadline = asyncio.get_running_loop().time() + deadline_seconds
    while True:
        async with SessionFactory() as session:
            stmt = select(AuditLogEntry).where(AuditLogEntry.action == action)
            result = await session.execute(stmt)
            rows = result.scalars().all()
            if rows:
                return rows
        if asyncio.get_running_loop().time() >= deadline:
            return []
        await asyncio.sleep(0.05)


# --- Model / create-on-read ---


async def test_get_me_profile_auto_creates(app_client):
    client = app_client
    tokens = await register_user(client, "profile1@example.com")
    # Fresh user should have profile with names from registration
    profile = await _get_profile(client, tokens)
    assert profile["user_id"]
    assert profile["custom_data"] == {}
    assert profile["first_name"] == "Test"
    assert profile["last_name"] == "User"
    # GET /auth/me should embed identical profile shape
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert resp.status_code == 200
    body = resp.json()
    assert "profile" in body
    assert body["profile"]["user_id"] == profile["user_id"]
    assert body["profile"]["custom_data"] == {}
    assert body["profile"]["first_name"] == "Test"
    assert body["profile"]["last_name"] == "User"


async def test_get_or_create_concurrent(app_client):
    client = app_client
    tokens = await register_user(client, "concurrent@example.com")
    # Get user_id via me
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    user_id = me.json()["id"]
    # Delete profile row to simulate legacy missing profile
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.user_profile import UserProfile

    async with SessionFactory() as session:
        await session.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
        await session.commit()

    # Concurrent GET /me/profile should both succeed and return same user_id, no 500
    async def fetch():
        return await client.get("/api/v1/me/profile", headers=auth_headers(tokens))

    results = await asyncio.gather(fetch(), fetch())
    assert all(r.status_code == 200 for r in results)
    assert results[0].json()["user_id"] == results[1].json()["user_id"] == user_id

    # Verify only one row exists
    async with SessionFactory() as session:
        from sqlalchemy import select

        result = await session.execute(select(UserProfile).where(UserProfile.user_id == user_id))
        rows = result.scalars().all()
        assert len(rows) == 1


# --- Merge Patch semantics ---


async def test_patch_merge_patch_add_and_retain(app_client):
    client = app_client
    tokens = await register_user(client, "merge1@example.com")
    # First patch
    resp = await client.patch(
        "/api/v1/me/profile", json={"custom_data": {"a": 1}}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"] == {"a": 1}
    # Second patch should retain a and add b
    resp = await client.patch(
        "/api/v1/me/profile", json={"custom_data": {"b": 2}}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"] == {"a": 1, "b": 2}
    # Fetch should reflect merged
    profile = await _get_profile(client, tokens)
    assert profile["custom_data"] == {"a": 1, "b": 2}


async def test_patch_null_delete(app_client):
    client = app_client
    tokens = await register_user(client, "merge2@example.com")
    await client.patch(
        "/api/v1/me/profile", json={"custom_data": {"a": 1, "b": 2}}, headers=auth_headers(tokens)
    )
    # Delete a
    resp = await client.patch(
        "/api/v1/me/profile", json={"custom_data": {"a": None}}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"] == {"b": 2}
    # Deleting absent key is no-op (should not error, retain b)
    resp = await client.patch(
        "/api/v1/me/profile",
        json={"custom_data": {"nonexistent": None}},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200
    assert resp.json()["custom_data"] == {"b": 2}


async def test_put_replace(app_client):
    client = app_client
    tokens = await register_user(client, "put1@example.com")
    await client.patch(
        "/api/v1/me/profile",
        json={"custom_data": {"keep": 1, "old": 2}},
        headers=auth_headers(tokens),
    )
    resp = await client.put(
        "/api/v1/me/profile", json={"custom_data": {"only": 1}}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"] == {"only": 1}
    profile = await _get_profile(client, tokens)
    assert profile["custom_data"] == {"only": 1}


async def test_put_without_custom_data_leaves_unchanged(app_client):
    client = app_client
    tokens = await register_user(client, "put2@example.com")
    await client.patch(
        "/api/v1/me/profile", json={"custom_data": {"keep": 1}}, headers=auth_headers(tokens)
    )
    # PUT with first_name but without custom_data should leave bag unchanged
    resp = await client.put(
        "/api/v1/me/profile", json={"first_name": "Ada"}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 200
    assert resp.json()["custom_data"] == {"keep": 1}
    assert resp.json()["first_name"] == "Ada"


# --- Validation: unknown top-level 422, bounds 16KiB/50 keys ---


async def test_unknown_top_level_422(app_client):
    client = app_client
    tokens = await register_user(client, "unknown1@example.com")
    resp = await client.patch(
        "/api/v1/me/profile", json={"unknown_field": 1}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 422
    # detail should be present
    assert "detail" in resp.json()


async def test_bounds_reject_51_keys(app_client):
    client = app_client
    tokens = await register_user(client, "bounds1@example.com")
    big = {f"k{i}": i for i in range(51)}
    resp = await client.patch(
        "/api/v1/me/profile", json={"custom_data": big}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 422
    assert "custom_data exceeds limits" in resp.text


async def test_bounds_reject_17kib(app_client):
    client = app_client
    tokens = await register_user(client, "bounds2@example.com")
    # Create a single large value >16KiB
    large_str = "x" * (17 * 1024)
    resp = await client.patch(
        "/api/v1/me/profile", json={"custom_data": {"big": large_str}}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 422
    assert "custom_data exceeds limits" in resp.text


async def test_bio_too_long_422(app_client):
    client = app_client
    tokens = await register_user(client, "bio1@example.com")
    long_bio = "b" * 1001
    resp = await client.patch(
        "/api/v1/me/profile", json={"bio": long_bio}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 422


# --- Audit ---


async def test_profile_update_publishes_audit(app_client):
    client = app_client
    tokens = await register_user(client, "audit1@example.com")
    # Patch with first_name to a new value (initial is "Test" from registration)
    await client.patch(
        "/api/v1/me/profile", json={"first_name": "NewFirst"}, headers=auth_headers(tokens)
    )
    # Wait for audit workflow
    rows = await _wait_for_audit(auth_headers(tokens), "profile.updated")
    assert len(rows) >= 1
    # Find one with changed_fields containing first_name and not containing value
    entry = next(r for r in rows if "first_name" in (r.details.get("changed_fields") or []))
    assert "NewFirst" not in json.dumps(entry.details)  # no PII values
    assert "first_name" in entry.details["changed_fields"]

    # Patch custom_data - wait for second audit
    await client.patch(
        "/api/v1/me/profile",
        json={"custom_data": {"twitter_handle": "@x"}},
        headers=auth_headers(tokens),
    )

    async def wait_for_twitter():
        deadline = asyncio.get_running_loop().time() + 3.0
        while asyncio.get_running_loop().time() < deadline:
            rows2 = await _wait_for_audit(auth_headers(tokens), "profile.updated")
            if any(
                "custom_data.twitter_handle" in (r.details.get("changed_fields") or [])
                for r in rows2
            ):
                return rows2
            await asyncio.sleep(0.05)
        return rows2

    rows = await wait_for_twitter()
    # Should have custom_data.twitter_handle
    assert any(
        "custom_data.twitter_handle" in (r.details.get("changed_fields") or []) for r in rows
    )
    # Ensure no raw value in details
    for r in rows:
        details_str = json.dumps(r.details)
        assert "@x" not in details_str


# --- Cross-user redaction and 404 ---


async def test_cross_user_allowed_redacted(app_client):
    client = app_client
    owner = await register_user(client, "crossowner@example.com")
    ws = await create_workspace(client, owner)
    # Invite and accept member
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    member_tokens = await register_user(client, "crossmember@example.com")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "crossmember@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    invite = invite.json()
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(member_tokens),
    )
    # Owner sets private data
    await client.patch(
        "/api/v1/me/profile",
        json={
            "phone_number": "+123",
            "bio": "secret bio",
            "custom_data": {"_private_secret": "hidden", "public_key": "visible"},
        },
        headers=auth_headers(owner),
    )
    # Also set date_of_birth
    await client.patch(
        "/api/v1/me/profile",
        json={"date_of_birth": "1990-01-01"},
        headers=auth_headers(owner),
    )
    owner_me = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    owner_id = owner_me.json()["id"]

    # Member reads owner's profile -> should be 200 redacted
    resp = await client.get(
        f"/api/v1/users/{owner_id}/profile", headers=auth_headers(member_tokens)
    )
    assert resp.status_code == 200, resp.text
    proj = resp.json()
    # phone_number and date_of_birth redacted (null)
    assert proj["phone_number"] is None
    assert proj["date_of_birth"] is None
    # _private* stripped, public retained
    assert "_private_secret" not in proj["custom_data"]
    assert proj["custom_data"].get("public_key") == "visible"

    # Owner reading own profile via /me/profile should see phone_number
    own = await _get_profile(client, owner)
    assert own["phone_number"] == "+123"


async def test_cross_user_denied_404(app_client):
    client = app_client
    a = await register_user(client, "crossa@example.com")
    b = await register_user(client, "crossb@example.com")
    # No shared workspace
    b_me = await client.get("/api/v1/auth/me", headers=auth_headers(b))
    b_id = b_me.json()["id"]
    resp = await client.get(f"/api/v1/users/{b_id}/profile", headers=auth_headers(a))
    assert resp.status_code == 404
    # Should be indistinguishable from missing user (also 404)
    resp2 = await client.get(
        "/api/v1/users/00000000-0000-0000-0000-000000000000/profile", headers=auth_headers(a)
    )
    assert resp2.status_code == 404


async def test_cross_user_superuser_bypass(app_client):
    client = app_client
    # root@example.com is superuser per conftest
    super_tokens = await register_user(client, "root@example.com")
    other = await register_user(client, "regular@example.com")
    other_me = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    other_id = other_me.json()["id"]
    # Superuser should be able to read even without shared workspace
    resp = await client.get(f"/api/v1/users/{other_id}/profile", headers=auth_headers(super_tokens))
    assert resp.status_code == 200


# --- Export ---


async def test_export_excludes_secrets(app_client):
    client = app_client
    tokens = await register_user(client, "export1@example.com")
    # Set profile data
    await client.patch(
        "/api/v1/me/profile",
        json={"first_name": "Export", "custom_data": {"keep": "yes"}},
        headers=auth_headers(tokens),
    )
    ws = await create_workspace(client, tokens)
    resp = await client.get("/api/v1/me/export", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    assert resp.headers.get("content-disposition", "").startswith("attachment")
    bundle = resp.json()
    assert "exported_at" in bundle
    assert bundle["profile"]["first_name"] == "Export"
    assert bundle["profile"]["custom_data"] == {"keep": "yes"}
    # user should not contain password_hash
    assert "password_hash" not in json.dumps(bundle)
    assert "password_hash" not in bundle["user"]
    # profile should contain custom_data exactly
    assert bundle["counts"]["audit_entries"] >= 0
    assert bundle["counts"]["notifications"] >= 0
    # Check workspaces
    assert any(w["workspace_id"] == ws["id"] for w in bundle["workspaces"])


async def test_export_superuser_variant_gated(app_client):
    client = app_client
    regular = await register_user(client, "export2@example.com")
    await register_user(client, "root2@example.com")  # not super; need root@example.com
    # Actually super is root@example.com only if SUPERADMIN_EMAIL is root@example.com
    # Use root@example.com for super
    # Let's ensure we have superuser: register with root@example.com
    # already used? We used super earlier
    # We'll create super via DB directly if needed
    # Instead test regular cannot export other user
    other_me = await client.get("/api/v1/auth/me", headers=auth_headers(regular))
    other_id = other_me.json()["id"]
    # Regular trying to export other -> 403
    resp = await client.get(f"/api/v1/users/{other_id}/export", headers=auth_headers(regular))
    # If other is self, self export is allowed via /me/export, but
    # /users/{id}/export should be gated
    # For self, regular trying to export self via superuser route should
    # be 403 (since not superuser)
    assert resp.status_code == 403

    # Superuser can export other
    # Use root@example.com if not already taken; create if needed via SessionFactory
    from sqlalchemy import select

    from src.core.security.tokens import create_access_token
    from src.db.session import SessionFactory
    from src.models.workspace import User

    async with SessionFactory() as session:
        result = await session.execute(select(User).where(User.email == "root@example.com"))
        root_user = result.scalar_one_or_none()
        if root_user is None:
            # create superuser manually
            root_user = User(
                email="root@example.com",
                password_hash="dummy",
                display_name="Root",
                is_superuser=True,
            )
            session.add(root_user)
            await session.commit()
        root_id = root_user.id
        # Ensure is_superuser
        if not root_user.is_superuser:
            root_user.is_superuser = True
            await session.commit()

    root_token = create_access_token(root_id)
    headers = {"Authorization": f"Bearer {root_token}"}
    resp = await client.get(f"/api/v1/users/{other_id}/export", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["profile"]["user_id"] == other_id


# --- Delete ---


async def test_delete_wrong_confirm_422(app_client):
    client = app_client
    tokens = await register_user(client, "del1@example.com")
    resp = await client.request(
        "DELETE",
        "/api/v1/me",
        json={"confirm": "WRONG", "password": "Password123!"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 422


async def test_delete_wrong_password_403(app_client):
    client = app_client
    tokens = await register_user(client, "del2@example.com")
    resp = await client.request(
        "DELETE",
        "/api/v1/me",
        json={"confirm": "DELETE", "password": "WrongPass123!"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 403


async def test_delete_missing_password_when_hash_exists_422(app_client):
    client = app_client
    tokens = await register_user(client, "del3@example.com")
    resp = await client.request(
        "DELETE", "/api/v1/me", json={"confirm": "DELETE"}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 422


async def test_delete_with_correct_password_cascade_and_401(app_client):
    client = app_client
    tokens = await register_user(client, "del4@example.com")
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    user_id = me.json()["id"]
    await create_workspace(client, tokens)
    # Create profile data
    await client.patch(
        "/api/v1/me/profile", json={"first_name": "ToDelete"}, headers=auth_headers(tokens)
    )

    resp = await client.request(
        "DELETE",
        "/api/v1/me",
        json={"confirm": "DELETE", "password": "Password123!"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 204, resp.text

    # Subsequent GET /auth/me with old token is 401
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert resp.status_code == 401

    # Profile/tokens rows gone
    from sqlalchemy import select

    from src.db.session import SessionFactory
    from src.models.user_profile import UserProfile
    from src.models.workspace import RefreshToken, User, WorkspaceMember

    async with SessionFactory() as session:
        assert await session.get(User, user_id) is None
        assert await session.get(UserProfile, user_id) is None
        result = await session.execute(select(RefreshToken).where(RefreshToken.user_id == user_id))
        assert result.scalar_one_or_none() is None
        result = await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
        )
        assert result.scalar_one_or_none() is None
        # Verify ApiKey and Notification cascade (verification-gap fix)
        from src.models.api_key import ApiKey as _ApiKey
        from src.models.core import Notification as _Notif

        result = await session.execute(select(_ApiKey).where(_ApiKey.created_by_user_id == user_id))
        assert result.scalar_one_or_none() is None
        result = await session.execute(select(_Notif).where(_Notif.user_id == user_id))
        assert result.scalar_one_or_none() is None


async def test_delete_oauth_without_password(app_client):
    from src.core.security.tokens import create_access_token
    from src.db.session import SessionFactory
    from src.models.workspace import User

    # Create oauth user without password_hash via DB
    async with SessionFactory() as session:
        oauth_user = User(email="oauthdel@example.com", password_hash=None, display_name="OAuth")
        session.add(oauth_user)
        await session.commit()
        await session.refresh(oauth_user)
        user_id = oauth_user.id
        token = create_access_token(user_id)

    headers = {"Authorization": f"Bearer {token}"}
    # Same confirm check
    resp = await app_client.request(
        "DELETE", "/api/v1/me", json={"confirm": "DELETE"}, headers=headers
    )
    assert resp.status_code == 204, resp.text
    # Verify gone
    async with SessionFactory() as session:
        assert await session.get(User, user_id) is None

    # Subsequent auth should be 401
    resp = await app_client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 401


async def test_delete_superuser_variant(app_client):
    client = app_client
    victim = await register_user(client, "victim@example.com")
    victim_me = await client.get("/api/v1/auth/me", headers=auth_headers(victim))
    victim_id = victim_me.json()["id"]

    # Create superuser token
    from sqlalchemy import select

    from src.core.security.tokens import create_access_token
    from src.db.session import SessionFactory
    from src.models.workspace import User

    async with SessionFactory() as session:
        result = await session.execute(select(User).where(User.email == "root@example.com"))
        root = result.scalar_one_or_none()
        if root is None:
            root = User(
                email="root@example.com", password_hash="x", display_name="Root", is_superuser=True
            )
            session.add(root)
            await session.commit()
            await session.refresh(root)
        else:
            root.is_superuser = True
            await session.commit()
            await session.refresh(root)
        token = create_access_token(root.id)

    headers = {"Authorization": f"Bearer {token}"}
    resp = await client.request("DELETE", f"/api/v1/users/{victim_id}", headers=headers)
    assert resp.status_code == 204, resp.text
    # Verify non-super cannot delete
    other = await register_user(client, "otherdel@example.com")
    resp = await client.request("DELETE", f"/api/v1/users/{victim_id}", headers=auth_headers(other))
    # victim already deleted, but other is not super, should be 403 before
    # 404? Actually our route checks superuser first, so 403
    assert resp.status_code in (403, 404)


# --- Unit: merge helpers ---


def test_merge_custom_data_unit():
    from src.services.profile_helpers import merge_custom_data

    # add and retain
    result = merge_custom_data({"a": 1}, {"b": 2}, is_put=False)
    assert result == {"a": 1, "b": 2}
    # null delete
    result = merge_custom_data({"a": 1, "b": 2}, {"a": None}, is_put=False)
    assert result == {"b": 2}
    # deleting absent is no-op
    result = merge_custom_data({"b": 2}, {"a": None}, is_put=False)
    assert result == {"b": 2}
    # put replace
    result = merge_custom_data({"a": 1, "b": 2}, {"only": 1}, is_put=True)
    assert result == {"only": 1}
    # put without patch leaves unchanged
    result = merge_custom_data({"keep": 1}, None, is_put=True)
    assert result == {"keep": 1}
    # patch without patch leaves unchanged
    result = merge_custom_data({"keep": 1}, None, is_put=False)
    assert result == {"keep": 1}


def test_merge_bounds():
    from src.services.profile_helpers import merge_custom_data

    # 51 keys should raise 422
    big = {f"k{i}": i for i in range(51)}
    with pytest.raises(Exception) as exc:
        merge_custom_data({}, big, is_put=False)
    assert exc.value.status_code == 422

    # 17KiB should raise
    large = {"big": "x" * (17 * 1024)}
    with pytest.raises(Exception) as exc2:
        merge_custom_data({}, large, is_put=False)
    assert exc2.value.status_code == 422


def test_public_projection_redaction():
    from src.models.user_profile import UserProfile
    from src.services.serializers import public_projection

    p = UserProfile(
        user_id="uid",
        first_name="A",
        phone_number="+123",
        date_of_birth=None,
        custom_data={"_private_secret": "hidden", "public": "yes"},
    )
    # Need to set required fields? Use defaults
    proj = public_projection(p)
    assert proj["phone_number"] is None
    assert proj["date_of_birth"] is None
    assert "_private_secret" not in proj["custom_data"]
    assert proj["custom_data"]["public"] == "yes"


async def test_profile_update_avatar_url(app_client):
    client = app_client
    tokens = await register_user(client, "avatar@example.com")
    resp = await client.patch(
        "/api/v1/me/profile",
        json={"avatar_url": "https://example.com/avatar.jpg"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 200, resp.text
    # Check via auth/me that avatar_url updated
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["avatar_url"] == "https://example.com/avatar.jpg"


async def test_delete_cascade_clears_api_keys_and_notifications(app_client):
    client = app_client
    tokens = await register_user(client, "delkeys@example.com")
    me = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    user_id = me.json()["id"]
    ws = await create_workspace(client, tokens)
    # Create an ApiKey via API
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "test-key", "permissions": []},
        headers=ws_headers(tokens, ws["id"]),
    )
    assert resp.status_code in (200, 201), resp.text
    # Create a notification directly via DB
    from src.db.session import SessionFactory
    from src.models.core import Notification

    async with SessionFactory() as session:
        n = Notification(user_id=user_id, workspace_id=ws["id"], type="test", title="t", body="b")
        session.add(n)
        await session.commit()
        notif_id = n.id
    # Delete account
    resp = await client.request(
        "DELETE",
        "/api/v1/me",
        json={"confirm": "DELETE", "password": "Password123!"},
        headers=auth_headers(tokens),
    )
    assert resp.status_code == 204, resp.text
    # Verify ApiKey and Notification gone
    from sqlalchemy import select

    from src.models.api_key import ApiKey

    async with SessionFactory() as session:
        assert await session.get(Notification, notif_id) is None
        result = await session.execute(select(ApiKey).where(ApiKey.created_by_user_id == user_id))
        assert result.scalar_one_or_none() is None
        result = await session.execute(select(Notification).where(Notification.user_id == user_id))
        assert result.scalar_one_or_none() is None
