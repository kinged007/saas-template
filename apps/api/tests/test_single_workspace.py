"""Single-workspace mode (SINGLE_WORKSPACE=1).

First login/register creates the workspace (owned by whoever arrives first,
normally the superadmin); every later login/register auto-joins the oldest
workspace with the role named by SINGLE_WORKSPACE_DEFAULT_ROLE (viewer by
default). Extra workspace creation and workspace deletion are rejected while
the flag is on.
"""

import pytest

from src.settings import settings
from tests.conftest import (
    auth_headers,
    break_single_workspace_join,
    create_workspace,
    login,
    register_user,
)


@pytest.fixture(autouse=True)
def _default_role_is_viewer(monkeypatch):
    # `settings` is a module singleton built at import, so a developer's
    # SINGLE_WORKSPACE_DEFAULT_ROLE (env or .env) would reach these tests.
    monkeypatch.setattr(settings, "single_workspace_default_role", "viewer")


@pytest.fixture
def single_workspace_on(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", True)
    yield
    monkeypatch.setattr(settings, "single_workspace", False)


def _spy_limiter(monkeypatch) -> list[tuple[str, str]]:
    """Record the limiter calls the next request makes. Returns the live list.

    The calls are recorded but not forwarded: the global limiter is shared
    across tests, and an assertion about *which* branch charged or reset does
    not need the window to keep enforcing.
    """
    calls: list[tuple[str, str]] = []

    class _Spy:
        def check(self, key: str) -> None:
            calls.append(("check", key))

        def fail(self, key: str) -> None:
            calls.append(("fail", key))

        def reset(self, key: str) -> None:
            calls.append(("reset", key))

    monkeypatch.setattr("src.api.routes.auth.get_auth_limiter", lambda: _Spy())
    return calls


async def test_register_creates_single_workspace(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200
    body = me.json()
    assert len(body["workspaces"]) == 1
    assert body["workspaces"][0]["role"] == "owner"
    assert body["single_workspace"] is True


async def test_second_register_joins_same_workspace(app_client, single_workspace_on):
    first = await register_user(app_client, "first@example.com")
    me1 = await app_client.get("/api/v1/auth/me", headers=auth_headers(first))
    ws_id = me1.json()["workspaces"][0]["id"]

    second = await register_user(app_client, "second@example.com")
    me2 = await app_client.get("/api/v1/auth/me", headers=auth_headers(second))
    assert me2.status_code == 200
    assert len(me2.json()["workspaces"]) == 1
    assert me2.json()["workspaces"][0]["id"] == ws_id
    assert me2.json()["workspaces"][0]["role"] == "viewer"


async def test_login_joins_single_workspace(app_client, single_workspace_on):
    await register_user(app_client, "first@example.com")
    await register_user(app_client, "second@example.com")
    tokens = await login(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert len(me.json()["workspaces"]) == 1


async def test_create_second_workspace_rejected(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    resp = await app_client.post(
        "/api/v1/workspaces", json={"name": "Second"}, headers=auth_headers(tokens)
    )
    assert resp.status_code == 403


async def test_delete_workspace_rejected(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws_id = me.json()["workspaces"][0]["id"]
    resp = await app_client.delete(
        f"/api/v1/workspaces/{ws_id}",
        headers={**auth_headers(tokens), "X-Workspace-ID": ws_id},
    )
    assert resp.status_code == 403


async def _first_workspace(app_client) -> tuple[dict, str]:
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws = me.json()["workspaces"][0]
    return tokens, ws["id"]


async def test_configured_system_role_is_granted(app_client, single_workspace_on, monkeypatch):
    monkeypatch.setattr(settings, "single_workspace_default_role", "editor")
    _, ws_id = await _first_workspace(app_client)
    tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "editor")]


async def test_configured_custom_role_is_granted(app_client, single_workspace_on, monkeypatch):
    tokens, ws_id = await _first_workspace(app_client)
    headers = {**auth_headers(tokens), "X-Workspace-ID": ws_id}
    resp = await app_client.post(
        "/api/v1/roles", json={"name": "ops", "permissions": []}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    monkeypatch.setattr(settings, "single_workspace_default_role", "ops")

    joined = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(joined))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "ops")]


async def test_role_created_with_padded_name_is_granted(
    app_client, single_workspace_on, monkeypatch
):
    # The role is created through a normal API call with padding; stripping
    # on write is what keeps it matchable as the configured default.
    tokens, ws_id = await _first_workspace(app_client)
    headers = {**auth_headers(tokens), "X-Workspace-ID": ws_id}
    resp = await app_client.post(
        "/api/v1/roles", json={"name": "  ops  ", "permissions": []}, headers=headers
    )
    assert resp.status_code in (200, 201), resp.text
    monkeypatch.setattr(settings, "single_workspace_default_role", "ops")

    joined = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(joined))
    assert [(w["id"], w["role"]) for w in me.json()["workspaces"]] == [(ws_id, "ops")]


async def test_custom_default_role_cannot_manage_existing_members(
    app_client, single_workspace_on, monkeypatch
):
    # The .env.example / settings.py note is only true because these paths
    # check the role name, not the permission list.
    tokens, ws_id = await _first_workspace(app_client)
    headers = {**auth_headers(tokens), "X-Workspace-ID": ws_id}
    created = await app_client.post(
        "/api/v1/roles",
        json={"name": "ops", "permissions": ["member:read", "member:create", "member:update"]},
        headers=headers,
    )
    assert created.status_code in (200, 201), created.text
    ops_id = created.json()["id"]
    monkeypatch.setattr(settings, "single_workspace_default_role", "ops")

    joined = await register_user(app_client, "ops@example.com")
    ops = {**auth_headers(joined), "X-Workspace-ID": ws_id}
    members = await app_client.get("/api/v1/members", headers=headers)
    assert members.status_code == 200, members.text
    target = next(m for m in members.json() if m["email"] == "ops@example.com")

    # Assigning a role to a new member is permission-gated, so the open
    # permission list is enough.
    invited = await app_client.post(
        "/api/v1/invitations", json={"email": "new@example.com", "role_id": ops_id}, headers=ops
    )
    assert invited.status_code == 201, invited.text

    # Changing an existing member's role is name-gated, so it is not.
    resp = await app_client.patch(
        f"/api/v1/members/{target['membership_id']}", json={"role_id": ops_id}, headers=ops
    )
    assert resp.status_code == 403, resp.text

    # Neither is suspending or reactivating one.
    for action in ("suspend", "reactivate"):
        resp = await app_client.post(
            f"/api/v1/members/{target['membership_id']}/{action}", headers=ops
        )
        assert resp.status_code == 403, (action, resp.text)

    # Nor transferring ownership, which needs "owner" rather than "owner"/"admin".
    resp = await app_client.post(
        f"/api/v1/workspaces/{ws_id}/transfer",
        json={"new_owner_membership_id": target["membership_id"]},
        headers=ops,
    )
    assert resp.status_code == 403, resp.text


async def test_unknown_role_name_falls_back_to_viewer(app_client, single_workspace_on, monkeypatch):
    from src.db.session import SessionFactory
    from src.models.workspace import Role

    _tokens, ws_id = await _first_workspace(app_client)
    # A workspace created before the case-insensitive name check (#328) can hold
    # `Owner` beside the seeded `owner`; neither auto-joins a newcomer.
    async with SessionFactory() as session:
        session.add(
            Role(
                workspace_id=ws_id,
                name="Owner",
                description=None,
                permissions=[],
                system=False,
            )
        )
        await session.commit()

    for i, value in enumerate(["", "   ", "nope", "owner", "Owner"]):
        monkeypatch.setattr(settings, "single_workspace_default_role", value)
        tokens = await register_user(app_client, f"newcomer{i}@example.com")
        me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
        assert me.json()["workspaces"][0]["role"] == "viewer", value


async def test_relogin_keeps_existing_member_role(app_client, single_workspace_on, monkeypatch):
    await _first_workspace(app_client)
    second = await register_user(app_client, "second@example.com")
    monkeypatch.setattr(settings, "single_workspace_default_role", "editor")
    resp = await app_client.post(
        "/api/v1/auth/login",
        json={"email": "second@example.com", "password": "Password123!"},
    )
    assert resp.status_code == 200, resp.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(resp.json()))
    assert me.json()["workspaces"][0]["role"] == "viewer"
    assert second["access_token"]


async def test_flag_off_keeps_current_behavior(app_client):
    assert settings.single_workspace is False
    tokens = await register_user(app_client, "plain@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["workspaces"] == []
    assert me.json()["single_workspace"] is False
    ws = await create_workspace(app_client, tokens)
    assert ws["id"]


async def test_refresh_joins_single_workspace(app_client, single_workspace_on, monkeypatch):
    # Registered before the flag was enabled: refresh heals the membership.
    monkeypatch.setattr(settings, "single_workspace", False)
    tokens = await register_user(app_client, "early@example.com")
    monkeypatch.setattr(settings, "single_workspace", True)
    first = await register_user(app_client, "first@example.com")
    me1 = await app_client.get("/api/v1/auth/me", headers=auth_headers(first))
    ws_id = me1.json()["workspaces"][0]["id"]

    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(resp.json()))
    assert [w["id"] for w in me.json()["workspaces"]] == [ws_id]
    # A successful refresh must clear the window, not charge it. The limiter
    # has to be spied on to see that: the refresh key is ip:token_hash and
    # rotation retires the presented token, so every rotation lands on a fresh
    # key and a charge on the way out could never reach a window.
    calls = _spy_limiter(monkeypatch)
    again = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": resp.json()["refresh_token"]}
    )
    assert again.status_code == 200, again.text
    assert [op for op, _ in calls] == ["check", "reset"], calls


async def test_join_survives_missing_viewer_role(app_client, single_workspace_on):
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.workspace import Role

    first = await register_user(app_client, "first@example.com")
    me1 = await app_client.get("/api/v1/auth/me", headers=auth_headers(first))
    ws_id = me1.json()["workspaces"][0]["id"]
    async with SessionFactory() as session:
        await session.execute(delete(Role).where(Role.workspace_id == ws_id, Role.name == "viewer"))
        await session.commit()
    # No 500: login succeeds and the newcomer still joins (fallback role).
    tokens = await register_user(app_client, "second@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert [w["id"] for w in me.json()["workspaces"]] == [ws_id]


async def test_refresh_refuses_pair_when_account_deleted_mid_rotation(app_client, monkeypatch):
    # The real race, no stub of the lookup under test: the account is deleted
    # out-of-band from a second session after rotate_refresh committed the new
    # token row, so the token is live and its owner is gone. Default mode has
    # no join to re-read the user, so this is where the pair used to escape.
    # The delete lands before the audit publish that follows, which still names
    # the deleted row as its actor, so this test also rides on the AuditLog
    # actor FK rules. It pins the guard, not the FK.
    from sqlalchemy import delete

    from src.db.session import SessionFactory
    from src.models.workspace import User
    from src.services.auth import AuthService

    assert settings.single_workspace is False
    tokens = await register_user(app_client, "vanishing@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    user_id = me.json()["id"]
    issue_tokens = AuthService.issue_tokens

    async def _delete_owner_then_issue(self, user, **kwargs):
        pair = await issue_tokens(self, user, **kwargs)
        async with SessionFactory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        return pair

    monkeypatch.setattr(AuthService, "issue_tokens", _delete_owner_then_issue)
    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "account no longer exists"
    assert "access_token" not in resp.json()
    assert "set-cookie" not in resp.headers


async def test_refresh_fails_closed_when_the_owner_re_read_raises(app_client, monkeypatch):
    # The existence check is a precondition for issuing a pair, so it cannot sit
    # under the join's best-effort handler: a re-read that raises used to be
    # logged and the caller still got 200 with a live pair.
    from src.services.auth import AuthService

    tokens = await register_user(app_client, "vanishing@example.com")

    async def _boom(self, refresh_token):
        raise RuntimeError("read failed")

    monkeypatch.setattr(AuthService, "get_user_by_refresh_token", _boom)
    with pytest.raises(RuntimeError):
        await app_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )


async def test_refresh_account_gone_charges_rate_limiter(
    app_client, single_workspace_on, monkeypatch
):
    # Every sibling 401 on refresh charges the limiter; the account-gone 401
    # has to as well. What the charge buys here is bookkeeping and a brake if
    # the guard ever regresses: the key is ip:token_hash and the rotation has
    # already retired the presented token, so a deleted account is not
    # throttled by it (that attempt dies in rotate_refresh instead).
    from src.services.auth import AuthService

    monkeypatch.setattr(settings, "auth_rate_limit_max_attempts", 1)
    tokens = await register_user(app_client, "newcomer@example.com")

    async def _no_owner(self, refresh_token):
        return None

    monkeypatch.setattr(AuthService, "get_user_by_refresh_token", _no_owner)
    gone = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert gone.status_code == 401, gone.text
    again = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert again.status_code == 429, again.text


async def _gone_user_is_gone(app_client, monkeypatch, entry: str):
    """Call one token entry point with the account gone after the join's rollback.

    The join failure is real (rollback runs, instances expire), so the only
    thing left to fake is the re-read that follows it. get_user has no other
    consumer on these paths: rotate_refresh uses session.get, and
    get_user_by_refresh_token runs before the helper.
    """
    from src.services.auth import AuthService

    await break_single_workspace_join(app_client)
    # Registered with the join already broken: the entry point under test is
    # the first call that sees the account gone.
    tokens = await register_user(app_client, "newcomer@example.com")

    async def _gone(self, user_id):
        return None

    monkeypatch.setattr(AuthService, "get_user", _gone)
    calls = _spy_limiter(monkeypatch)
    if entry == "register":
        resp = await app_client.post(
            "/api/v1/auth/register",
            json={
                "email": "late@example.com",
                "password": "Password123!",
                "first_name": "Late",
                "last_name": "Arrival",
            },
        )
    elif entry == "login":
        resp = await app_client.post(
            "/api/v1/auth/login",
            json={"email": "newcomer@example.com", "password": "Password123!"},
        )
    elif entry == "refresh":
        resp = await app_client.post(
            "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
        )
    else:
        pytest.fail(f"unknown entry point: {entry}")
    assert resp.status_code == 401, resp.text
    assert resp.json()["detail"] == "account no longer exists"
    assert "access_token" not in resp.json()
    if entry != "register":
        # Both throttled entry points charge the limiter on this 401 instead of
        # resetting the window. On login that is the whole point: the key is
        # ip:email and stays reusable, so a reset would leave it unthrottled.
        # /register has no limiter at all.
        assert [op for op, _ in calls] == ["check", "fail"], calls


@pytest.mark.parametrize("entry", ["login", "refresh"])
async def test_account_gone_surfaces_401_on_every_token_entry_point(
    app_client, single_workspace_on, monkeypatch, entry
):
    # Pins the guard on the entry points that return an existing account. They
    # propagate it only because neither call is wrapped in a try:; wrap either
    # the way refresh was wrapped and the guard silently stops propagating.
    await _gone_user_is_gone(app_client, monkeypatch, entry)


async def test_register_propagates_the_join_guard(app_client, single_workspace_on, monkeypatch):
    # /register calls the same join helper, so the guard propagates there too.
    # The status reads wrong for a registration — the account was committed
    # milliseconds earlier, and a 401 tells the client to log in, which it
    # cannot do with an account it never learned the id of. Kept as its own
    # named test so it reads as inherited helper behavior, not a contract.
    await _gone_user_is_gone(app_client, monkeypatch, "register")


async def test_login_survives_join_failure(app_client, single_workspace_on):
    # A failed join is log-only: the rollback it needs expires every loaded
    # instance, so the reads after it must not be lazy loads.
    await break_single_workspace_join(app_client)
    await register_user(app_client, "newcomer@example.com")

    tokens = await login(app_client, "newcomer@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    assert me.json()["workspaces"] == []
    assert me.json()["single_workspace"] is True


async def test_refresh_survives_join_failure(app_client, single_workspace_on):
    await break_single_workspace_join(app_client)
    tokens = await register_user(app_client, "newcomer@example.com")

    resp = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    # The join's rollback runs after the rotation: the rotated token has to
    # outlive it, and the one it replaced has to stay dead.
    rotated = resp.json()["refresh_token"]
    assert rotated != tokens["refresh_token"]
    again = await app_client.post("/api/v1/auth/refresh", json={"refresh_token": rotated})
    assert again.status_code == 200, again.text
    stale = await app_client.post(
        "/api/v1/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert stale.status_code == 401, stale.text


async def test_register_survives_join_failure(app_client, single_workspace_on, caplog):
    await break_single_workspace_join(app_client)
    tokens = await register_user(app_client, "newcomer@example.com")

    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.status_code == 200, me.text
    assert me.json()["workspaces"] == []
    # The operator gets the real reason, not the configured default role.
    assert "has no non-owner role to join" in caplog.text


async def test_delete_nonexistent_returns_404_in_single_mode(app_client, single_workspace_on):
    tokens = await register_user(app_client, "first@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    ws_id = me.json()["workspaces"][0]["id"]
    resp = await app_client.delete(
        "/api/v1/workspaces/00000000-0000-0000-0000-000000000000",
        headers={**auth_headers(tokens), "X-Workspace-ID": ws_id},
    )
    assert resp.status_code == 404


async def test_oldest_workspace_wins(app_client, single_workspace_on, monkeypatch):
    # Pre-existing workspaces: auto-join picks the oldest, extras stay hidden.
    monkeypatch.setattr(settings, "single_workspace", False)
    tokens = await register_user(app_client, "owner@example.com")
    ws1 = await create_workspace(app_client, tokens, "First")
    ws2 = await create_workspace(app_client, tokens, "Second")
    assert ws1["id"] != ws2["id"]
    monkeypatch.setattr(settings, "single_workspace", True)

    newcomer = await register_user(app_client, "newcomer@example.com")
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(newcomer))
    assert [w["id"] for w in me.json()["workspaces"]] == [ws1["id"]]
