"""Malformed workspace ids must be client errors, never 500s.

A bad id reaches StringUUID.process_bind_param, which calls uuid.UUID(value)
unguarded. SQLAlchemy wraps the resulting ValueError in StatementError, and
with no global exception handler on the app it surfaces as a 500.
"""

from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)

MALFORMED = "not-a-uuid"
# Syntactically valid but matches nothing — the repo's idiom for a missing row.
UNKNOWN_UUID = "00000000-0000-0000-0000-000000000000"


def _assert_uuid_rejected(resp, loc: str) -> None:
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"][0]["type"] == "uuid_parsing", resp.text
    assert resp.json()["detail"][0]["loc"] == loc, resp.text


async def test_malformed_workspace_header_is_422_not_500(app_client):
    """The issue's repro: valid path id, malformed X-Workspace-ID."""
    client = app_client
    user = await register_user(client)
    ws = await create_workspace(client, user)

    headers = auth_headers(user)
    headers["X-Workspace-ID"] = MALFORMED
    resp = await client.patch(f"/api/v1/workspaces/{ws['id']}", json={"name": "x"}, headers=headers)

    _assert_uuid_rejected(resp, ["header", "X-Workspace-ID"])


async def test_malformed_workspace_header_on_required_dependency(app_client):
    """get_current_workspace_id — the 400-on-missing branch is untouched."""
    client = app_client
    user = await register_user(client)
    await create_workspace(client, user)

    resp = await client.get("/api/v1/roles", headers=ws_headers(user, MALFORMED))

    _assert_uuid_rejected(resp, ["header", "X-Workspace-ID"])


async def test_malformed_workspace_header_on_optional_dependency(app_client):
    """get_optional_workspace_id also reaches UUID-bound queries."""
    client = app_client
    user = await register_user(client)

    resp = await client.get("/api/v1/workspaces", headers=ws_headers(user, MALFORMED))

    _assert_uuid_rejected(resp, ["header", "X-Workspace-ID"])


async def test_malformed_workspace_path_param_is_422_not_500(app_client):
    """require_existing_workspace resolves from the path param, not the header."""
    client = app_client
    user = await register_user(client)
    ws = await create_workspace(client, user)

    resp = await client.get(f"/api/v1/workspaces/{MALFORMED}", headers=ws_headers(user, ws["id"]))

    _assert_uuid_rejected(resp, ["path", "workspace_id"])


async def test_missing_workspace_header_still_400(app_client):
    """A missing header is a 400, distinct from a malformed one."""
    client = app_client
    user = await register_user(client)
    await create_workspace(client, user)

    resp = await client.get("/api/v1/roles", headers=auth_headers(user))

    assert resp.status_code == 400


async def test_well_formed_unknown_workspace_header_reaches_membership_check(app_client):
    """Validation must not swallow the membership check for a valid-but-absent id."""
    client = app_client
    user = await register_user(client)

    resp = await client.get("/api/v1/roles", headers=ws_headers(user, UNKNOWN_UUID))

    assert resp.status_code == 403


async def test_well_formed_workspace_header_still_works(app_client):
    """The happy path is unaffected: a real id returns 200."""
    client = app_client
    user = await register_user(client)
    ws = await create_workspace(client, user)

    resp = await client.get("/api/v1/roles", headers=ws_headers(user, ws["id"]))

    assert resp.status_code == 200
