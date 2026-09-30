"""Workspace-level 2FA enforcement (docs/FEATURE_FLAGS.md: require_2fa)."""

from src.core.security.totp import current_code, secret_from_base32
from tests.conftest import (
    auth_headers,
    create_workspace,
    login,
    register_user,
    ws_headers,
)

SECURITY_URL = "/api/v1/workspaces/{ws}/security"


async def _enable_2fa(client, headers):
    resp = await client.post("/api/v1/auth/2fa/setup", headers=headers)
    assert resp.status_code == 200, resp.text
    setup = resp.json()
    b32 = setup["otpauth_uri"].split("secret=")[1].split("&")[0]
    resp = await client.post(
        "/api/v1/auth/2fa/enable",
        json={"setup_token": setup["setup_token"], "code": current_code(secret_from_base32(b32))},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["backup_codes"]


async def _set_require_2fa(client, headers, workspace_id, value):
    resp = await client.patch(
        SECURITY_URL.format(ws=workspace_id), json={"require_2fa": value}, headers=headers
    )
    return resp


async def _invite_viewer(client, owner_tokens, workspace_id, email):
    owner_headers = ws_headers(owner_tokens, workspace_id)
    roles = await client.get("/api/v1/roles", headers=owner_headers)
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": viewer["id"]},
        headers=owner_headers,
    )
    assert resp.status_code == 201, resp.text
    member_tokens = await register_user(client, email)
    resp = await client.post(
        "/api/v1/invitations/accept",
        params={"token": resp.json()["token"]},
        headers=auth_headers(member_tokens),
    )
    assert resp.status_code == 200, resp.text
    return member_tokens


# ----------------------------------------------------------------- setting


async def test_require_2fa_defaults_off(app_client):
    client = app_client
    tokens = await register_user(client, "sec-default@example.com")
    ws = await create_workspace(client, tokens, name="sec-ws-1")
    assert ws["require_2fa"] is False


async def test_set_require_2fa_round_trips(app_client):
    client = app_client
    tokens = await register_user(client, "sec-set@example.com")
    ws = await create_workspace(client, tokens, name="sec-ws-2")
    headers = ws_headers(tokens, ws["id"])

    resp = await _set_require_2fa(client, headers, ws["id"], True)
    assert resp.status_code == 200, resp.text
    assert resp.json()["require_2fa"] is True

    # The owner has no 2FA, so the gate now refuses their session — including
    # the read-back. The setting route itself still answers (see
    # test_admin_can_turn_the_requirement_back_off).
    assert (await client.get(f"/api/v1/workspaces/{ws['id']}", headers=headers)).status_code == 403

    # turning it back off clears the flag rather than storing `false`
    resp = await _set_require_2fa(client, headers, ws["id"], False)
    assert resp.json()["require_2fa"] is False
    resp = await client.get(f"/api/v1/workspaces/{ws['id']}", headers=headers)
    assert resp.json()["require_2fa"] is False
    listed = await client.get("/api/v1/workspaces", headers=auth_headers(tokens))
    entry = next(w for w in listed.json() if w["id"] == ws["id"])
    assert entry["require_2fa"] is False


async def test_set_require_2fa_rejects_non_bool(app_client):
    client = app_client
    tokens = await register_user(client, "sec-bool@example.com")
    ws = await create_workspace(client, tokens, name="sec-ws-3")
    resp = await _set_require_2fa(client, ws_headers(tokens, ws["id"]), ws["id"], "yes")
    assert resp.status_code == 422, resp.text


async def test_set_require_2fa_requires_workspace_update(app_client):
    client = app_client
    tokens = await register_user(client, "sec-owner@example.com")
    ws = await create_workspace(client, tokens, name="sec-ws-4")
    member = await _invite_viewer(client, tokens, ws["id"], "sec-viewer@example.com")

    resp = await _set_require_2fa(client, ws_headers(member, ws["id"]), ws["id"], True)
    assert resp.status_code == 403, resp.text


# ------------------------------------------------------------- enforcement


async def test_flag_off_allows_session_without_2fa(app_client):
    client = app_client
    owner = await register_user(client, "sec-off-owner@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-5")
    member = await _invite_viewer(client, owner, ws["id"], "sec-off-member@example.com")

    # With the requirement off, a viewer reads normally: the 2FA gate is not
    # in the way (viewers do hold role:read in this template).
    resp = await client.get("/api/v1/roles", headers=ws_headers(member, ws["id"]))
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/conversations", headers=ws_headers(member, ws["id"]))
    assert resp.status_code == 200, resp.text

    resp = await client.get("/api/v1/auth/me", headers=auth_headers(member))
    assert resp.status_code == 200, resp.text


async def test_flag_on_blocks_session_without_2fa(app_client):
    client = app_client
    owner = await register_user(client, "sec-on-owner@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-6")
    await _invite_viewer(client, owner, ws["id"], "sec-on-member@example.com")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)
    member = await login(client, "sec-on-member@example.com")

    # A viewer is blocked on the roles list they could otherwise read, and the
    # code tells the client to send them to the 2FA setup flow.
    resp = await client.get("/api/v1/roles", headers=ws_headers(member, ws["id"]))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "2fa_required_for_workspace"


async def test_flag_on_allows_session_that_passed_2fa(app_client):
    client = app_client
    owner = await register_user(client, "sec-pass-owner@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-7")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)

    # The owner is a member of a workspace that now requires 2FA and has none.
    resp = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    assert resp.status_code == 403, resp.text

    owner = await login(client, "sec-pass-owner@example.com")
    backup_codes = await _enable_2fa(client, auth_headers(owner))

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "sec-pass-owner@example.com", "password": "Password123!"},
    )
    challenge = resp.json()["detail"]["challenge_token"]
    resp = await client.post(
        "/api/v1/auth/2fa/login",
        json={"challenge_token": challenge, "code": backup_codes[0]},
    )
    assert resp.status_code == 200, resp.text
    verified = resp.json()

    resp = await client.get("/api/v1/roles", headers=ws_headers(verified, ws["id"]))
    assert resp.status_code == 200, resp.text


async def test_verdict_survives_refresh(app_client):
    client = app_client
    owner = await register_user(client, "sec-refresh@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-8")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)
    owner = await login(client, "sec-refresh@example.com")
    backup_codes = await _enable_2fa(client, auth_headers(owner))

    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "sec-refresh@example.com", "password": "Password123!"},
    )
    challenge = resp.json()["detail"]["challenge_token"]
    resp = await client.post(
        "/api/v1/auth/2fa/login",
        json={"challenge_token": challenge, "code": backup_codes[0]},
    )
    verified = resp.json()

    # Rotating must carry the verdict onto the new session, or the next access
    # token refresh would lock the user out of their own workspace.
    resp = await client.post(
        "/api/v1/auth/refresh", json={"refresh_token": verified["refresh_token"]}
    )
    assert resp.status_code == 200, resp.text
    rotated = resp.json()
    resp = await client.get("/api/v1/roles", headers=ws_headers(rotated, ws["id"]))
    assert resp.status_code == 200, resp.text

    # A password-only session still cannot rotate into access.
    other = await register_user(client, "sec-refresh-other@example.com")
    other_ws = await create_workspace(client, other, name="sec-ws-9")
    await _set_require_2fa(client, ws_headers(other, other_ws["id"]), other_ws["id"], True)
    resp = await client.get("/api/v1/roles", headers=ws_headers(other, other_ws["id"]))
    assert resp.status_code == 403, resp.text
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": other["refresh_token"]})
    assert resp.status_code == 200, resp.text
    rotated_plain = resp.json()
    resp = await client.get("/api/v1/roles", headers=ws_headers(rotated_plain, other_ws["id"]))
    assert resp.status_code == 403, resp.text


async def test_api_key_is_exempt(app_client):
    client = app_client
    owner = await register_user(client, "sec-key-owner@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-10")

    # Mint the key first: once the requirement is on, the owner's own session
    # is gated out and could not create one.
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": "ci", "permissions": ["role:read"]},
        headers=ws_headers(owner, ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    key = resp.json()["key"]

    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)

    # The owner's own session is blocked, but the key still works: it is a
    # server-side credential with no authenticator app. Minted with role:read
    # so the request gets past the permission check and reaches the gate.
    assert (
        await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    ).status_code == 403
    resp = await client.get(
        "/api/v1/roles", headers={"Authorization": f"Bearer {key}", "X-Workspace-ID": ws["id"]}
    )
    assert resp.status_code == 200, resp.text


async def test_turning_requirement_off_reopens_workspace(app_client):
    """The gate keys off the flag alone and clears with it.

    Driven through the service rather than the escape-hatch route, which
    test_admin_can_turn_the_requirement_back_off covers end to end.
    """
    client = app_client
    owner = await register_user(client, "sec-reopen@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-11")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)
    assert (
        await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    ).status_code == 403

    from src.db.session import SessionFactory
    from src.services.workspaces import WorkspaceService

    async with SessionFactory() as session:
        await WorkspaceService(session).set_require_2fa(ws["id"], require_2fa=False)

    resp = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    assert resp.status_code == 200, resp.text


async def test_admin_can_turn_the_requirement_back_off(app_client):
    """The escape hatch.

    An admin with no 2FA of their own turns the requirement on and is
    immediately gated out of the workspace. The route that manages the setting
    stays reachable, otherwise turning it on would be irreversible.
    """
    client = app_client
    owner = await register_user(client, "sec-escape@example.com")
    ws = await create_workspace(client, owner, name="sec-escape")
    headers = ws_headers(owner, ws["id"])

    assert (await _set_require_2fa(client, headers, ws["id"], True)).status_code == 200
    assert (await client.get("/api/v1/roles", headers=headers)).status_code == 403

    resp = await _set_require_2fa(client, headers, ws["id"], False)
    assert resp.status_code == 200, resp.text
    assert (await client.get("/api/v1/roles", headers=headers)).status_code == 200


async def test_enabling_2fa_mid_session_satisfies_the_gate(app_client):
    """Enrolling must not strand the user on the setup page.

    The user proves possession of the secret with a valid code, which is the
    same evidence a login challenge collects, so the session they are already
    in counts as verified. Otherwise enabling 2FA would bounce them straight
    back to the setup flow with no way forward.
    """
    client = app_client
    owner = await register_user(client, "sec-mid@example.com")
    ws = await create_workspace(client, owner, name="sec-mid")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)
    assert (
        await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    ).status_code == 403

    # Enrol from inside the blocked session, via the profile security page.
    await _enable_2fa(client, auth_headers(owner))
    resp = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    assert resp.status_code == 200, resp.text

    # And the verdict survives the next refresh.
    resp = await client.post("/api/v1/auth/refresh", json={"refresh_token": owner["refresh_token"]})
    assert resp.status_code == 200, resp.text
    resp = await client.get("/api/v1/roles", headers=ws_headers(resp.json(), ws["id"]))
    assert resp.status_code == 200, resp.text


async def test_user_scoped_routes_still_require_the_header(app_client):
    """Guard against a None workspace id reaching the gate.

    Notifications and received invitations depend on the *optional* workspace
    id, so the header can be absent. These routes reject that with 400 today;
    the gate must not turn the same request into a 403 security error, which
    would blame the user's 2FA state for a missing header.
    """
    client = app_client
    owner = await register_user(client, "sec-user-scope@example.com")
    ws = await create_workspace(client, owner, name="sec-user-scope")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)

    resp = await client.get("/api/v1/notifications", headers=auth_headers(owner))
    assert resp.status_code == 400, resp.text
    assert resp.json()["detail"] == "X-Workspace-ID header is required"

    # With the header present the user is gated, because that workspace does
    # require 2FA.
    resp = await client.get("/api/v1/notifications", headers=ws_headers(owner, ws["id"]))
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "2fa_required_for_workspace"


# ------------------------------------------------------------------- /me


async def test_me_reports_2fa_state(app_client):
    client = app_client
    owner = await register_user(client, "sec-me@example.com")
    ws = await create_workspace(client, owner, name="sec-ws-12")
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)

    resp = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    entry = next(w for w in resp.json()["workspaces"] if w["id"] == ws["id"])
    assert entry["require_2fa"] is True
    assert entry["two_factor_verified"] is False

    # Enabling 2FA stamps the session that did it; the workspace half is unchanged.
    owner = await login(client, "sec-me@example.com")
    await _enable_2fa(client, auth_headers(owner))
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    assert resp.status_code == 200, resp.text
    entry = next(w for w in resp.json()["workspaces"] if w["id"] == ws["id"])
    assert entry["two_factor_verified"] is True
    assert entry["require_2fa"] is True


async def test_me_verdict_agrees_with_the_gate_for_a_pre_enrolment_session(app_client):
    """/me must report the session verdict, not the user's 2FA state.

    A user who enrolled on one device still has other sessions that predate
    it. Those are password-only and the gate refuses them, so /me reporting
    "verified" there would leave the client showing a working app while every
    request 403s.
    """
    client = app_client
    early = await register_user(client, "sec-pre-enrol@example.com")
    ws = await create_workspace(client, early, name="sec-pre-enrol")
    # A second session, created before any enrolment; the enrolment below
    # stamps only the session that performs it.
    other = await login(client, "sec-pre-enrol@example.com")
    await _enable_2fa(client, auth_headers(other))
    await _set_require_2fa(client, ws_headers(other, ws["id"]), ws["id"], True)

    # TOTP is on for the user now, so a per-user flag would call this session
    # fine. The gate disagrees, and so must /me.
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(early))
    entry = next(w for w in resp.json()["workspaces"] if w["id"] == ws["id"])
    assert entry["two_factor_verified"] is False
    resp = await client.get("/api/v1/roles", headers=ws_headers(early, ws["id"]))
    assert resp.status_code == 403

    # The session that enrolled is verified, and the two agree again.
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(other))
    entry = next(w for w in resp.json()["workspaces"] if w["id"] == ws["id"])
    assert entry["two_factor_verified"] is True
    resp = await client.get("/api/v1/roles", headers=ws_headers(other, ws["id"]))
    assert resp.status_code == 200


async def test_disabling_2fa_clears_the_session_verdict(app_client):
    """The verdict means "this session cleared a challenge".

    With 2FA gone there is no challenge left to clear, so a session that
    proved 2FA earlier must not keep passing the gate — and /me must stop
    calling it verified, so client and server agree in both directions.
    """
    client = app_client
    owner = await register_user(client, "sec-disable@example.com")
    ws = await create_workspace(client, owner, name="sec-disable")
    await _enable_2fa(client, auth_headers(owner))
    await _set_require_2fa(client, ws_headers(owner, ws["id"]), ws["id"], True)
    assert (
        await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    ).status_code == 200

    resp = await client.post(
        "/api/v1/auth/2fa/disable",
        json={"password": "Password123!"},
        headers=auth_headers(owner),
    )
    assert resp.status_code == 204, resp.text
    assert (
        await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    ).status_code == 403
    resp = await client.get("/api/v1/auth/me", headers=auth_headers(owner))
    entry = next(w for w in resp.json()["workspaces"] if w["id"] == ws["id"])
    assert entry["two_factor_verified"] is False


async def test_transfer_is_gated_and_leaving_is_not(app_client):
    """The two workspace-scoped routes that carry no permission dependency.

    `POST /workspaces/{id}/transfer` is authorized by the owner *role*, so it
    has no `require_permission` to hang the gate off and calls
    `enforce_workspace_security` directly. `DELETE /workspaces/{id}/membership`
    is exempt on purpose: a member this setting refuses must still be able to
    leave a workspace that requires 2FA.
    """
    client = app_client
    owner = await register_user(client, "sec-transfer-owner@example.com")
    ws = await create_workspace(client, owner, name="sec-transfer")
    owner_headers = ws_headers(owner, ws["id"])
    await _invite_viewer(client, owner, ws["id"], "sec-transfer-member@example.com")
    leaver = await _invite_viewer(client, owner, ws["id"], "sec-transfer-leaver@example.com")

    # Read the target membership while the flag is still off — with it on, the
    # owner's own session cannot list members.
    members = (await client.get("/api/v1/members", headers=owner_headers)).json()
    target = next(m for m in members if m["email"] == "sec-transfer-member@example.com")
    transfer = {"new_owner_membership_id": target["membership_id"]}

    assert (await _set_require_2fa(client, owner_headers, ws["id"], True)).status_code == 200

    resp = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer", json=transfer, headers=owner_headers
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["detail"]["code"] == "2fa_required_for_workspace"

    # Leaving is exempt, so a member the gate refuses is not trapped.
    assert (
        await client.delete(
            f"/api/v1/workspaces/{ws['id']}/membership", headers=ws_headers(leaver, ws["id"])
        )
    ).status_code == 204

    # The refusal was the gate and not the route: with the requirement off the
    # very same call goes through.
    assert (await _set_require_2fa(client, owner_headers, ws["id"], False)).status_code == 200
    resp = await client.post(
        f"/api/v1/workspaces/{ws['id']}/transfer", json=transfer, headers=owner_headers
    )
    assert resp.status_code == 200, resp.text
