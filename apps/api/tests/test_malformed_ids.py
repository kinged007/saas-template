"""No route returns 500 when a path, query, body, or header id is malformed.

StringUUID's bind processor calls uuid.UUID(value) on any str bind, so a raw
"not-a-uuid" id that reaches a query raises StatementError -> 500. Every fixed
site validates the id before the lookup (route-boundary uuid_or_404, in the
service where an authorization check must keep running before the lookup —
invitations, or centrally in apply_query for query ids) and answers with the
status that id class already gets: 404 for path/header/body lookups, 400 where
a valid-but-unknown id is also a 400 (mark_read's message id, participants),
and 422 for query ids (InvalidQuery, the same class as any other bad query
parameter). Probes hit every fixed route with "not-a-uuid"; same failure class
and test shape as webhooks (PR #1430) and admin.
"""

from __future__ import annotations

import uuid

from src.core.permissions import MEMBER_CREATE
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)

BAD = "not-a-uuid"
VALID_ID = "00000000-0000-0000-0000-000000000000"


async def _owner_ws(app_client):
    """A session user owning a fresh workspace; returns (tokens, workspace_id)."""
    tokens = await register_user(app_client, "malformed-owner@example.com")
    ws = await create_workspace(app_client, tokens, name="Malformed Probes")
    return tokens, ws["id"]


async def _conversation(app_client, tokens, workspace_id) -> str:
    """Open a conversation owned by `tokens` with one joined peer participant."""
    roles = (await app_client.get("/api/v1/roles", headers=ws_headers(tokens, workspace_id))).json()
    role_id = next(r["id"] for r in roles if r["name"] == "viewer")
    invite = (
        await app_client.post(
            "/api/v1/invitations",
            json={"email": "malformed-peer@example.com", "role_id": role_id},
            headers=ws_headers(tokens, workspace_id),
        )
    ).json()
    peer = await register_user(app_client, "malformed-peer@example.com")
    accepted = await app_client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(peer),
    )
    assert accepted.status_code == 200, accepted.text
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    peer_id = (await app_client.get("/api/v1/auth/me", headers=auth_headers(peer))).json()["id"]
    resp = await app_client.post(
        "/api/v1/conversations",
        json={
            "title": "probe",
            "participant_user_ids": [me.json()["id"], peer_id],
            "initial_message": "hello",
        },
        headers=ws_headers(tokens, workspace_id),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


# (method, url, json body) — probed with the owner's bearer token and a valid
# X-Workspace-ID, so only the malformed path id can decide the status.
WORKSPACE_PROBES = [
    # api keys
    ("patch", f"/api/v1/api-keys/{BAD}", {"usage_quota": 5}),
    ("delete", f"/api/v1/api-keys/{BAD}", None),
    # conversations (the 8 id-carrying handlers)
    ("get", f"/api/v1/conversations/{BAD}", None),
    ("patch", f"/api/v1/conversations/{BAD}", {"title": "x"}),
    ("patch", f"/api/v1/conversations/{BAD}/participants", {"participant_user_ids": [VALID_ID]}),
    ("patch", f"/api/v1/conversations/{BAD}/read", {"last_read_message_id": VALID_ID}),
    ("patch", f"/api/v1/conversations/{BAD}/unread", None),
    ("patch", f"/api/v1/conversations/{BAD}/archive", {"archived": True}),
    ("get", f"/api/v1/conversations/{BAD}/messages", None),
    ("post", f"/api/v1/conversations/{BAD}/messages", {"body": "hi"}),
    # workspaces (path id)
    ("get", f"/api/v1/workspaces/{BAD}", None),
    ("patch", f"/api/v1/workspaces/{BAD}", {"name": "x"}),
    ("post", f"/api/v1/workspaces/{BAD}/transfer", {"new_owner_membership_id": VALID_ID}),
    ("delete", f"/api/v1/workspaces/{BAD}", None),
    ("delete", f"/api/v1/workspaces/{BAD}/membership", None),
    # members
    ("patch", f"/api/v1/members/{BAD}", {"role_id": VALID_ID}),
    ("post", f"/api/v1/members/{BAD}/suspend", None),
    ("post", f"/api/v1/members/{BAD}/reactivate", None),
    ("delete", f"/api/v1/members/{BAD}", None),
    # roles
    ("get", f"/api/v1/roles/{BAD}", None),
    ("patch", f"/api/v1/roles/{BAD}", {"name": "x"}),
    # workspace-scoped jobs
    ("get", f"/api/v1/jobs/{BAD}", None),
    ("patch", f"/api/v1/jobs/{BAD}", {"enabled": False}),
    ("post", f"/api/v1/jobs/{BAD}/execute", {}),
    ("get", f"/api/v1/jobs/{BAD}/runs", None),
    # notifications
    ("patch", f"/api/v1/notifications/{BAD}", {"acknowledged": True}),
    ("delete", f"/api/v1/notifications/{BAD}", None),
    # invitations (owner passes the service's role check, reaching the lookup)
    ("delete", f"/api/v1/invitations/{BAD}", None),
    ("post", f"/api/v1/invitations/{BAD}/resend", None),
    ("post", f"/api/v1/invitations/{BAD}/decline", None),
]


async def test_workspace_route_malformed_path_id_not_500(app_client):
    tokens, workspace_id = await _owner_ws(app_client)
    headers = ws_headers(tokens, workspace_id)
    for method, url, body in WORKSPACE_PROBES:
        resp = await app_client.request(method, url, json=body, headers=headers)
        # Workspace path ids are framework-validated UUID params (422);
        # every other probed route looks its id up as a string (404).
        # Either way the pinned property is the same: never a 500.
        expected = 422 if f"/api/v1/workspaces/{BAD}" in url else 404
        assert resp.status_code == expected, (method, url, resp.status_code, resp.text)


async def test_superuser_route_malformed_path_id_not_500(app_client):
    tokens = await register_user(app_client, "root@example.com")  # SUPERADMIN_EMAIL
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    assert me.json()["is_superuser"] is True
    headers = auth_headers(tokens)
    global_probes = [
        ("get", f"/api/v1/jobs/global/{BAD}", None),
        ("patch", f"/api/v1/jobs/global/{BAD}", {"enabled": False}),
        ("post", f"/api/v1/jobs/global/{BAD}/execute", {}),
        ("get", f"/api/v1/jobs/global/{BAD}/runs", None),
        ("get", f"/api/v1/jobs/runs/{BAD}", None),
        ("get", f"/api/v1/jobs/runs/{BAD}/logs", None),
    ]
    for method, url, body in global_probes:
        resp = await app_client.request(method, url, json=body, headers=headers)
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)


async def test_malformed_workspace_header_not_500(app_client):
    tokens, _workspace_id = await _owner_ws(app_client)
    headers = {**auth_headers(tokens), "X-Workspace-ID": BAD}
    # The header dependency is UUID-annotated, so a malformed value is a 422
    # (same contract as test_deps.py) on required and optional routes alike.
    for url in ("/api/v1/roles", "/api/v1/workspaces", "/api/v1/notifications"):
        resp = await app_client.get(url, headers=headers)
        assert resp.status_code == 422, (url, resp.status_code, resp.text)


async def test_malformed_query_ids_not_500(app_client):
    tokens, workspace_id = await _owner_ws(app_client)
    headers = ws_headers(tokens, workspace_id)
    # ?ids[]= / ?id= and a filter on a uuid-typed column reach the same bind;
    # the crud list layer rejects them as a bad query (422), not a bind error.
    probes = [
        f"/api/v1/audit?ids[]={BAD}",
        f"/api/v1/audit?id={BAD}",
        f"/api/v1/audit?filter[actor_user_id]={BAD}",
        f"/api/v1/members?ids[]={BAD}",
        f"/api/v1/members?filter[role_id]={BAD}",
        f"/api/v1/notifications?ids[]={BAD}",
        f"/api/v1/api-keys?ids[]={BAD}",
        f"/api/v1/invitations?id={BAD}",
        f"/api/v1/roles?ids[]={BAD}",
    ]
    for url in probes:
        resp = await app_client.get(url, headers=headers)
        assert resp.status_code == 422, (url, resp.status_code, resp.text)
    # Parity: a well-formed but unknown id is still just an empty page.
    resp = await app_client.get(f"/api/v1/audit?ids[]={VALID_ID}", headers=headers)
    assert resp.status_code == 200, (resp.status_code, resp.text)


async def test_superuser_malformed_query_ids_not_500(app_client):
    tokens = await register_user(app_client, "root@example.com")  # SUPERADMIN_EMAIL
    headers = auth_headers(tokens)
    for url in (
        f"/api/v1/admin/users?ids[]={BAD}",
        f"/api/v1/admin/workspaces?ids[]={BAD}",
        f"/api/v1/admin/audit?filter[actor_user_id]={BAD}&filter[workspace_id]={BAD}",
    ):
        resp = await app_client.get(url, headers=headers)
        assert resp.status_code == 422, (url, resp.status_code, resp.text)


async def _member_membership_id(app_client, tokens, workspace_id, email) -> str:
    """Invite + accept a viewer; returns their membership id."""
    roles = (await app_client.get("/api/v1/roles", headers=ws_headers(tokens, workspace_id))).json()
    invite = (
        await app_client.post(
            "/api/v1/invitations",
            json={"email": email, "role_id": next(r["id"] for r in roles if r["name"] == "viewer")},
            headers=ws_headers(tokens, workspace_id),
        )
    ).json()
    peer = await register_user(app_client, email)
    accepted = await app_client.post(
        "/api/v1/invitations/accept",
        params={"token": invite["token"]},
        headers=auth_headers(peer),
    )
    assert accepted.status_code == 200, accepted.text
    members = (
        await app_client.get("/api/v1/members", headers=ws_headers(tokens, workspace_id))
    ).json()
    return next(m["membership_id"] for m in members if m["email"] == email)


async def test_malformed_body_ids_keep_the_valid_unknown_status(app_client):
    tokens, workspace_id = await _owner_ws(app_client)
    headers = ws_headers(tokens, workspace_id)
    conversation_id = await _conversation(app_client, tokens, workspace_id)
    me = await app_client.get("/api/v1/auth/me", headers=auth_headers(tokens))
    membership_id = await _member_membership_id(
        app_client, tokens, workspace_id, "body-probe@example.com"
    )
    # Transfer and participant lookups 404/400 on an unknown id, as does an
    # unknown invitation role id. A malformed body id keeps the same status
    # instead of 500 — except role_id fields, which are UUID in the schema:
    # a malformed role_id is a 422 request error while a valid-but-unknown
    # role_id keeps the lookup status (404 member role, 400 invitation).
    probes = [
        (
            "post",
            f"/api/v1/workspaces/{workspace_id}/transfer",
            {"new_owner_membership_id": BAD},
            404,
        ),
        ("patch", f"/api/v1/members/{membership_id}", {"role_id": BAD}, 422),
        (
            "patch",
            f"/api/v1/conversations/{conversation_id}/participants",
            {"participant_user_ids": [BAD]},
            400,
        ),
        (
            "post",
            "/api/v1/conversations",
            {"title": "probe", "participant_user_ids": [BAD], "initial_message": "hi"},
            400,
        ),
        (
            "post",
            "/api/v1/invitations",
            {"email": "malformed-role@example.com", "role_id": BAD},
            422,
        ),
    ]
    for method, url, body, expected in probes:
        resp = await app_client.request(method, url, json=body, headers=headers)
        assert resp.status_code == expected, (method, url, resp.status_code, resp.text)
    # Parity: a well-formed but unknown id keeps the same status.
    parity = [
        (
            "post",
            f"/api/v1/workspaces/{workspace_id}/transfer",
            {"new_owner_membership_id": VALID_ID},
            404,
        ),
        ("patch", f"/api/v1/members/{membership_id}", {"role_id": VALID_ID}, 404),
        (
            "patch",
            f"/api/v1/conversations/{conversation_id}/participants",
            {"participant_user_ids": [me.json()["id"], VALID_ID]},
            400,
        ),
        (
            "post",
            "/api/v1/invitations",
            {"email": "unknown-role@example.com", "role_id": VALID_ID},
            400,
        ),
    ]
    for method, url, body, expected in parity:
        resp = await app_client.request(method, url, json=body, headers=headers)
        assert resp.status_code == expected, (method, url, resp.status_code, resp.text)


async def test_api_key_decline_malformed_invitation_id_404(app_client):
    # The API-key branch of the decline route guards the id itself, before its
    # own db.get; the service's invitation check runs after the lookup.
    tokens, workspace_id = await _owner_ws(app_client)
    created = (
        await app_client.post(
            "/api/v1/api-keys",
            json={"name": "decline-probe", "permissions": [MEMBER_CREATE]},
            headers=ws_headers(tokens, workspace_id),
        )
    ).json()
    headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": workspace_id}
    resp = await app_client.post(f"/api/v1/invitations/{BAD}/decline", headers=headers)
    assert resp.status_code == 404, (resp.status_code, resp.text)
    # Parity: a well-formed but unknown invitation id stays a 404.
    resp = await app_client.post(f"/api/v1/invitations/{VALID_ID}/decline", headers=headers)
    assert resp.status_code == 404, (resp.status_code, resp.text)


async def test_mark_read_malformed_body_message_id_400(app_client):
    tokens, workspace_id = await _owner_ws(app_client)
    conversation_id = await _conversation(app_client, tokens, workspace_id)
    resp = await app_client.patch(
        f"/api/v1/conversations/{conversation_id}/read",
        json={"last_read_message_id": BAD},
        headers=ws_headers(tokens, workspace_id),
    )
    assert resp.status_code == 400, (resp.status_code, resp.text)
    # A well-formed but unknown message id keeps the same 400.
    resp = await app_client.patch(
        f"/api/v1/conversations/{conversation_id}/read",
        json={"last_read_message_id": str(uuid.uuid4())},
        headers=ws_headers(tokens, workspace_id),
    )
    assert resp.status_code == 400, (resp.status_code, resp.text)
