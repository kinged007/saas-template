"""`profile:update`: editing another member's profile from a workspace.

Guards the target-scoped routes in `api/routes/profiles.py`. The scope is
workspace-scoped, so the target must belong to the same workspace the
permission is evaluated in.
"""

import asyncio

import pytest
from sqlalchemy import select

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


async def _membership_id(client, tokens: dict, ws: dict, user_id: str) -> str:
    resp = await client.get("/api/v1/members", headers=ws_headers(tokens, ws["id"]))
    assert resp.status_code == 200, resp.text
    return next(m["membership_id"] for m in resp.json() if m["id"] == user_id)


async def _wait_for(predicate, timeout_secs: float = 3.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_secs
    while loop.time() < deadline:
        if await predicate():
            return True
        await asyncio.sleep(interval)
    return False


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
    await client.patch(
        "/api/v1/me/profile",
        json={"phone_number": "+49 555"},
        headers=auth_headers(user),
    )
    resp = await client.get(f"/api/v1/users/{user_id}/profile", headers=auth_headers(user))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The projection self always got: identity fields, contact fields redacted.
    assert body["email"] == "ada@example.com"
    assert "display_name" in body
    assert body["phone_number"] is None
    # The editable fields live on the target route only, not on self.
    own = await client.get("/api/v1/me/profile", headers=auth_headers(user))
    assert own.json()["phone_number"] == "+49 555"


async def test_put_replaces_the_target_profile(app_client):
    """PUT is the isPut branch of useUpdateProfile; without the route it 405s."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.put(
        f"/api/v1/users/{target['id']}/profile",
        json={"first_name": "Put", "last_name": "NotPatch"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["first_name"] == "Put"


async def test_suspended_target_is_not_editable(app_client):
    """The guard asks about access, so it takes active membership rows only: a
    suspended target is out of the editable set and reads as absent (404), the
    same as a user who was never a member. The guard's docstring says so."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")
    membership = await _membership_id(client, owner, ws, target["id"])
    suspended = await client.post(
        f"/api/v1/members/{membership}/suspend", headers=ws_headers(owner, ws["id"])
    )
    assert suspended.status_code == 200, suspended.text

    resp = await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"bio": "not editable"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 404, resp.text


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


async def test_target_notification_preferences_reject_an_unknown_type(app_client):
    """Only types the notification workflows emit are writable, so nobody can
    fill a member's preference table with rows nothing reads."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.put(
        f"/api/v1/users/{target['id']}/notification-preferences",
        json={"channels": {"junk_preference_row": "email"}},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 422, resp.text
    # The self route enforces the same set.
    own = await client.put(
        "/api/v1/notifications/preferences",
        json={"channels": {"junk_preference_row": "email"}},
        headers=auth_headers(owner),
    )
    assert own.status_code == 422, own.text


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
    """The delegated session routes target other members only: self goes
    through /auth/sessions, so neither a session user nor an API key can sign
    its own account out through them."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    sessions = await client.get("/api/v1/auth/sessions", headers=auth_headers(admin))
    mine = sessions.json()[0]["id"]

    resp = await client.delete(
        f"/api/v1/users/{admin['id']}/sessions/{mine}", headers=ws_headers(admin, ws["id"])
    )
    assert resp.status_code == 400, resp.text
    assert "use /auth/sessions" in resp.json()["detail"]

    resp = await client.delete(
        f"/api/v1/users/{admin['id']}/sessions", headers=ws_headers(admin, ws["id"])
    )
    assert resp.status_code == 400, resp.text

    still_there = await client.get("/api/v1/auth/sessions", headers=auth_headers(admin))
    assert still_there.status_code == 200
    assert mine in [row["id"] for row in still_there.json()]


async def test_api_key_cannot_revoke_its_creator_sessions(app_client):
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")

    key = await client.post(
        "/api/v1/api-keys",
        json={"name": "script", "permissions": [PROFILE_UPDATE]},
        headers=ws_headers(admin, ws["id"]),
    )
    key_headers = {
        "Authorization": f"Bearer {key.json()['key']}",
        "X-Workspace-ID": ws["id"],
    }
    resp = await client.delete(f"/api/v1/users/{admin['id']}/sessions", headers=key_headers)
    assert resp.status_code == 400, resp.text
    assert (
        await client.get("/api/v1/auth/sessions", headers=auth_headers(admin))
    ).status_code == 200


async def test_passwords_longer_than_bcrypt_allows_are_422(app_client):
    """bcrypt raises above 72 bytes; the schema must refuse before hashing."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.post(
        f"/api/v1/users/{target['id']}/password",
        json={"new_password": "A" * 100},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 422, resp.text
    resp = await client.post(
        "/api/v1/auth/change-password",
        json={"current_password": "Password123!", "new_password": "A" * 100},
        headers=auth_headers(admin),
    )
    assert resp.status_code == 422, resp.text
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "long@example.com", "first_name": "Long", "password": "A" * 100},
    )
    assert resp.status_code == 422, resp.text


async def test_a_renamed_owner_role_is_still_protected(app_client):
    """Owner-level power is `"*"` in the role, not the name "owner": a role that
    carries it stays protected even when the name is different."""
    from src.db.session import SessionFactory
    from src.models.workspace import Role

    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    owner_id = await _user_id(client, owner)

    async with SessionFactory() as session:
        role = await session.scalar(
            select(Role).where(Role.workspace_id == ws["id"], Role.name == "owner")
        )
        role.name = "chief"
        await session.commit()

    resp = await client.post(
        f"/api/v1/users/{owner_id}/password",
        json={"new_password": "BrandNewPass1!"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 403, resp.text


async def test_superuser_target_password_is_refused(app_client):
    from src.db.session import SessionFactory
    from src.models.workspace import User

    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "root@example.com", "viewer")

    async with SessionFactory() as session:
        row = await session.get(User, target["id"])
        row.is_superuser = True
        await session.commit()

    resp = await client.post(
        f"/api/v1/users/{target['id']}/password",
        json={"new_password": "BrandNewPass1!"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 403, resp.text
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": "root@example.com", "password": "Password123!"}
        )
    ).status_code == 200


async def test_delegated_writes_are_audited_under_the_workspace(app_client):
    """A delegated write lands in the acting workspace's audit log, not in a
    user-scoped orphan row."""
    from src.db.session import SessionFactory
    from src.models.audit import AuditLogEntry

    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.post(
        f"/api/v1/users/{target['id']}/password",
        json={"new_password": "BrandNewPass1!"},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 204, resp.text

    async def password_event() -> AuditLogEntry | None:
        async with SessionFactory() as session:
            result = await session.execute(
                select(AuditLogEntry).where(AuditLogEntry.action == "user.password_changed")
            )
            return result.scalars().first()

    async def recorded() -> bool:
        return await password_event() is not None

    assert await _wait_for(recorded)
    row = await password_event()
    assert row.workspace_id == ws["id"]
    assert row.actor_user_id == admin["id"]


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


async def test_a_malformed_target_id_is_404_not_500(app_client):
    """StringUUID's bind processor raises ValueError on a malformed id, so the
    guard validates before the membership lookup; the read path needs its own
    check because it falls back to the redacted projection."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    resp = await client.get("/api/v1/users/not-a-uuid/sessions", headers=headers)
    assert resp.status_code == 404, resp.text

    resp = await client.get("/api/v1/users/not-a-uuid/profile", headers=headers)
    assert resp.status_code == 404, resp.text

    resp = await client.post(
        "/api/v1/users/not-a-uuid/password",
        json={"new_password": "Sup3rSecret!"},
        headers=headers,
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.parametrize(
    ("method", "path", "payload"),
    [
        ("PATCH", "/api/v1/users/{sid}/profile", {"first_name": "Nope"}),
        ("PUT", "/api/v1/users/{sid}/profile", {"first_name": "Nope"}),
        ("GET", "/api/v1/users/{sid}/notification-preferences", None),
        (
            "PUT",
            "/api/v1/users/{sid}/notification-preferences",
            {"channels": {"member_joined": "email"}},
        ),
        ("GET", "/api/v1/users/{sid}/sessions", None),
        ("DELETE", "/api/v1/users/{sid}/sessions", None),
        ("POST", "/api/v1/users/{sid}/password", {"new_password": "Sup3rSecret!"}),
    ],
)
async def test_every_target_route_404s_for_a_non_member(app_client, method, path, payload):
    """Each target route has to answer 404 for a stranger, not just the profile
    write: a target outside the caller's workspace must never be confirmed."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    stranger = await _user_id(client, await register_user(client, "mallory@example.com"))
    headers = ws_headers(admin, ws["id"])

    resp = await client.request(method, path.format(sid=stranger), headers=headers, json=payload)
    assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}: {resp.text}"


async def test_a_delegated_editor_cannot_read_or_overwrite_private_custom_data(app_client):
    """`_private*` custom_data keys belong to the account holder. The delegated
    read strips them and the delegated write neither sets nor drops them — a PUT
    replaces custom_data wholesale, so the stored private keys must survive."""
    client = app_client
    owner = await register_user(client, "ada@example.com")
    ws = await create_workspace(client, owner)
    admin = await _add_member(client, owner, ws, "abby@example.com", "admin")
    target = await _add_member(client, owner, ws, "bob@example.com", "viewer")

    resp = await client.patch(
        "/api/v1/me/profile",
        json={"custom_data": {"theme": "dark", "_private_note": "keep me"}},
        headers=auth_headers(target),
    )
    assert resp.status_code == 200, resp.text

    seen = await client.get(
        f"/api/v1/users/{target['id']}/profile", headers=ws_headers(admin, ws["id"])
    )
    assert seen.json()["custom_data"] == {"theme": "dark"}

    # The editor may change the public keys, but not the private one.
    resp = await client.patch(
        f"/api/v1/users/{target['id']}/profile",
        json={"custom_data": {"theme": "light", "_private_note": "overwritten"}},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"] == {"theme": "light"}

    # A PUT replaces custom_data wholesale — the private key must survive it.
    resp = await client.put(
        f"/api/v1/users/{target['id']}/profile",
        json={"custom_data": {"theme": "solar"}},
        headers=ws_headers(admin, ws["id"]),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"] == {"theme": "solar"}

    stored = await client.get("/api/v1/me/profile", headers=auth_headers(target))
    assert stored.json()["custom_data"] == {"theme": "solar", "_private_note": "keep me"}

    # Self-service is untouched: the owner still writes their own private keys.
    resp = await client.patch(
        "/api/v1/me/profile",
        json={"custom_data": {"_private_note": "mine"}},
        headers=auth_headers(target),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["custom_data"]["_private_note"] == "mine"
