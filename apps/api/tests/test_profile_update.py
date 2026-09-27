"""`profile:update`: editing another member's profile from a workspace.

Guards the target-scoped routes in `api/routes/profiles.py`. The scope is
workspace-scoped, so the target must be an active member of the same workspace
the permission is evaluated in.
"""

from src.core.permissions import ALL_PERMISSIONS, PROFILE_UPDATE, permissions_for_role
from tests.conftest import (
    auth_headers,
    create_workspace,
    login,
    register_user,
    ws_headers,
)


async def _user_id(client, tokens: dict) -> str:
    """register_user returns a token pair; the id lives on /auth/me."""
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def _add_member(client, owner_tokens, ws, email: str, role_name: str) -> dict:
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))
    role = next(r for r in roles.json() if r["name"] == role_name)
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role["id"]},
        headers=ws_headers(owner_tokens, ws["id"]),
    )
    invite = resp.json()
    user = await register_user(client, email)
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(user),
    )
    return {**user, "id": await _user_id(client, user)}


# ------------------------------------------------------------- catalog


def test_profile_update_is_a_separate_scope_from_member_update():
    assert PROFILE_UPDATE == "profile:update"
    assert PROFILE_UPDATE in ALL_PERMISSIONS
    assert "member:update" != PROFILE_UPDATE


def test_profile_update_defaults_to_admin_and_owner():
    assert PROFILE_UPDATE in permissions_for_role("owner")
    assert PROFILE_UPDATE in permissions_for_role("admin")
    assert PROFILE_UPDATE not in permissions_for_role("editor")
    assert PROFILE_UPDATE not in permissions_for_role("viewer")


async def test_permission_catalog_exposes_profile_update(app_client):
    owner = await register_user(app_client, "ada@example.com")
    ws = await create_workspace(app_client, owner)
    resp = await app_client.get(
        "/api/v1/roles/permission-catalog", headers=ws_headers(owner, ws["id"])
    )
    assert resp.status_code == 200, resp.text
    assert PROFILE_UPDATE in resp.json()["permissions"]


# ------------------------------------------------------------- profile


async def test_admin_gets_unredacted_target_profile(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"phone_number": "+49 555", "date_of_birth": "1990-04-01"},
        headers=ws_headers(admin, ws["id"]),
    )
    resp = await client.get(
        f"/api/v1/users/{target['id']}/profile", headers=ws_headers(admin, ws["id"])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phone_number"] == "+49 555"
    assert body["date_of_birth"] == "1990-04-01"
    # Workspace memberships are superuser-only and must never ride along.
    assert "workspaces" not in body
    assert "roles" not in body


async def test_co_member_without_the_scope_keeps_the_redacted_projection(app_client):
    """A viewer (no profile:update) reads the same redacted shape as before."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")
    viewer = await _add_member(client, owner, ws, "eve@example.com", "viewer")

    # Give the target fields the redacted projection must hide.
    await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"phone_number": "+49 555", "date_of_birth": "1990-04-01"},
        headers=ws_headers(owner, ws["id"]),
    )

    resp = await client.get(
        f"/api/v1/users/{target['id']}/profile", headers=ws_headers(viewer, ws["id"])
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["phone_number"] is None
    assert body["date_of_birth"] is None
    # The owner holds profile:update and sees them.
    full = await client.get(
        f"/api/v1/users/{target['id']}/profile", headers=ws_headers(owner, ws["id"])
    )
    assert full.json()["phone_number"] == "+49 555"
    assert full.json()["date_of_birth"] == "1990-04-01"


async def test_admin_updates_target_profile_fields(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"first_name": "Renamed", "bio": "edited by an admin", "phone_number": "+1 555"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Renamed"
    assert resp.json()["bio"] == "edited by an admin"

    stored = await client.get("/api/v1/me/profile", headers=auth_headers(target))
    assert stored.json()["first_name"] == "Renamed"
    assert stored.json()["phone_number"] == "+1 555"


async def test_editor_cannot_update_target_profile(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    editor = await _add_member(client, owner, ws, "eve@example.com", "editor")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"first_name": "Nope"},
        headers=ws_headers(editor, ws["id"]),
    )
    assert resp.status_code == 403, resp.text
    assert PROFILE_UPDATE in resp.json()["detail"]


async def test_target_outside_the_callers_workspace_is_404(app_client):
    """Writes to a non-member 404. The read falls back to the redacted
    projection, so it never confirms more than any co-member already sees."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    acme = await create_workspace(client, owner, "Acme")
    globex = await create_workspace(client, owner, "Globex")
    admin = await _add_member(client, owner, acme, "abby@example.com", "admin")
    stranger = await _user_id(client, await register_user(client, "mallory@example.com"))
    await client.patch(
        f"/api/v1/users/{admin['id']}/profile",
        json={"phone_number": "+49 555"},
        headers=ws_headers(owner, acme["id"]),
    )

    resp = await client.patch(
        f"/api/v1/users/{stranger}/profile",
        json={"first_name": "Nope"},
        headers=ws_headers(admin, acme["id"]),
    )
    assert resp.status_code == 404, resp.text

    # The owner holds every permission in Globex, but the admin is not a member
    # of it, so the read stays redacted there.
    resp = await client.get(
        f"/api/v1/users/{admin['id']}/profile", headers=ws_headers(owner, globex["id"])
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["phone_number"] is None
    # ... while the same caller inside Acme sees the full profile.
    full = await client.get(
        f"/api/v1/users/{admin['id']}/profile", headers=ws_headers(owner, acme["id"])
    )
    assert full.json()["phone_number"] == "+49 555"


async def test_self_profile_routes_are_unchanged(app_client):
    client = app_client
    user = await register_user(client, "ada@example.com")
    await create_workspace(client, user)
    resp = await client.patch(
        "/api/v1/me/profile",
        json={"first_name": "Ada"},
        headers=auth_headers(user),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Ada"

    # No workspace header needed, no permission needed.
    user_id = await _user_id(client, user)
    resp = await client.get(f"/api/v1/users/{user_id}/profile", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    assert resp.json()["phone_number"] is None


# ------------------------------------------------- notification settings


async def test_admin_updates_target_notification_preferences(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.put(
        f"/api/v1/users/{target['id']}/notification-preferences",
        json={"channels": {"member_joined": "email"}, "digest_enabled": True},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["channels"]["member_joined"] == "email"
    assert resp.json()["digest_enabled"] is True

    own = await client.get("/api/v1/notifications/preferences", headers=auth_headers(target))
    assert own.json()["channels"]["member_joined"] == "email"
    assert own.json()["digest_enabled"] is True


async def test_target_notification_preferences_reject_an_unknown_channel(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.put(
        f"/api/v1/users/{target['id']}/notification-preferences",
        json={"channels": {"member_joined": "carrier-pigeon"}},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 422, resp.text


async def test_editor_cannot_read_target_notification_preferences(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    editor = await _add_member(client, owner, ws, "eve@example.com", "editor")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.get(
        f"/api/v1/users/{target['id']}/notification-preferences",
        headers=ws_headers(editor, ws["id"]),
    )
    assert resp.status_code == 403, resp.text


# ------------------------------------------------------------- security


async def test_admin_sets_target_password_and_kills_target_sessions(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")
    await login(client, "bob@example.com")  # a second live session for the target

    resp = await client.post(
        f"/api/v1/users/{target['id']}/password",
        json={"new_password": "BrandNewPass1!"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 204, resp.text

    # Old password stops working, the new one works.
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "bob@example.com", "password": "Password123!"}
        )
    ).status_code == 401
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "bob@example.com", "password": "BrandNewPass1!"}
        )
    ).status_code == 200

    # The session the admin did not touch is still the admin's.
    assert (await client.get("/api/v1/me/profile", headers=auth_headers(admin))).status_code == 200


async def test_admin_cannot_set_a_password_without_proof_of_ownership(app_client):
    """Self, the workspace owner and superusers are off limits: setting their
    password is account takeover, not profile editing."""
    client = app_client
    owner_tokens = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner_tokens)
    admin = await _add_member(client, owner_tokens, ws, "abby@example.com", "admin")
    await _add_member(client, owner_tokens, ws, "bob@example.com", "viewer")
    owner = await _user_id(client, owner_tokens)
    # A superuser who is also a workspace member, so the membership check passes
    # and the superuser guard is what refuses.
    superuser = await _add_member(client, owner_tokens, ws, "root@example.com", "viewer")

    for subject in (admin["id"], owner, superuser["id"]):
        resp = await client.post(
            f"/api/v1/users/{subject}/password",
            json={"new_password": "BrandNewPass1!"},
            headers=ws_headers(admin, ws["id"]),
        )
        assert resp.status_code == 403, f"target {subject}: {resp.text}"

    # Nobody's password actually changed.
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "ada@example.com", "password": "Password123!"}
        )
    ).status_code == 200
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "abby@example.com", "password": "Password123!"}
        )
    ).status_code == 200


async def test_admin_lists_and_revokes_target_sessions(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    listed = await client.get(
        f"/api/v1/users/{target['id']}/sessions", headers=ws_headers(admin, ws["id"])
    )
    assert listed.status_code == 200, listed.text
    rows = listed.json()
    assert rows, "the invited member has at least the session from register/accept"
    # A delegated view has no "current" session — the caller's own does.
    assert all(r["current"] is False for r in rows)

    resp = await client.delete(
        f"/api/v1/users/{target['id']}/sessions/{rows[0]['id']}",
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 204, resp.text

    after = await client.get(
        f"/api/v1/users/{target['id']}/sessions", headers=ws_headers(admin, ws["id"])
    )
    assert rows[0]["id"] not in [r["id"] for r in after.json()]


async def test_admin_revokes_every_target_session(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.delete(
        f"/api/v1/users/{target['id']}/sessions", headers=ws_headers(admin, ws["id"])
    )
    assert resp.status_code == 204, resp.text
    assert (
        await client.get(
            f"/api/v1/users/{target['id']}/sessions", headers=ws_headers(admin, ws["id"])
        )
    ).json() == []


async def test_admin_cannot_revoke_another_users_sessions(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    sessions = await client.get("/api/v1/auth/sessions", headers=auth_headers(admin))
    mine = sessions.json()[0]["id"]

    resp = await client.delete(
        f"/api/v1/users/{admin['id']}/sessions/{mine}", headers=ws_headers(admin, ws["id"])
    )
    assert resp.status_code == 400, resp.text  # cannot revoke your own current session
    assert (
        await client.get("/api/v1/auth/sessions", headers=auth_headers(admin))
    ).status_code == 200


async def test_editor_cannot_list_target_sessions(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    editor = await _add_member(client, owner, ws, "eve@example.com", "editor")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.get(
        f"/api/v1/users/{target['id']}/sessions", headers=ws_headers(editor, ws["id"])
    )
    assert resp.status_code == 403, resp.text


# ------------------------------------------------------------- api keys


async def test_api_key_holding_profile_update_can_edit_a_member(app_client):
    """The scope works for API keys, scoped to the workspace they name."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    key = await client.post(
        "/api/v1/api-keys",
        json={"name": "script", "permissions": [PROFILE_UPDATE, "member:read"]},
        headers=ws_headers(owner, ws["id"]),
    )
    key_headers = {
        "Authorization": f"Bearer {key.json()['key']}",
        "X-Workspace-ID": ws["id"],
    }

    resp = await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"first_name": "Via API key"},
        headers=key_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Via API key"


async def test_api_key_without_profile_update_cannot_edit_a_member(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    key = await client.post(
        "/api/v1/api-keys",
        json={"name": "reader", "permissions": ["member:read"]},
        headers=ws_headers(owner, ws["id"]),
    )
    key_headers = {
        "Authorization": f"Bearer {key.json()['key']}",
        "X-Workspace-ID": ws["id"],
    }

    resp = await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"first_name": "Nope"},
        headers=key_headers,
    )
    assert resp.status_code == 403, resp.text
    assert PROFILE_UPDATE in resp.json()["detail"]
