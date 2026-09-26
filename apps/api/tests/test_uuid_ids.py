"""Malformed ids in StringUUID columns must be 404, not 500.

`StringUUID.process_bind_param` (`src/db/base.py`) parses the id while
SQLAlchemy binds it, so an unparseable id raises before any route-level
`except` can see it. `src/api/errors.py` maps that one failure to 404.

These cases run through the real app, so the handler is exercised the way it
runs in production. `test_other_statement_errors_stay_500` covers the other
direction: a database failure that is not a bad id must not be masked.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from sqlalchemy.exc import StatementError

from src.api.errors import is_malformed_uuid_error
from tests.conftest import auth_headers, create_workspace, login, register_user, ws_headers

MALFORMED = "not-a-uuid"


@pytest.fixture
async def owner(app_client):
    """An owner with a workspace, plus plain and workspace-scoped headers."""
    tokens = await register_user(app_client, "owner@example.com")
    workspace = await create_workspace(app_client, tokens, "Acme")
    return auth_headers(tokens), ws_headers(tokens, workspace["id"])


async def test_malformed_id_returns_404_on_every_route(app_client, owner):
    auth, wsh = owner
    cases = [
        ("get", "/api/v1/workspaces/{m}", wsh, None),
        ("patch", "/api/v1/workspaces/{m}", wsh, {"name": "Renamed"}),
        ("delete", "/api/v1/workspaces/{m}", wsh, None),
        ("delete", "/api/v1/workspaces/{m}/membership", wsh, None),
        ("get", "/api/v1/roles/{m}", wsh, None),
        ("patch", "/api/v1/roles/{m}", wsh, {"name": "Renamed"}),
        ("patch", "/api/v1/members/{m}", wsh, {"role_id": str(uuid.uuid4())}),
        ("delete", "/api/v1/members/{m}", wsh, None),
        ("delete", "/api/v1/invitations/{m}", wsh, None),
        ("post", "/api/v1/invitations/{m}/decline", wsh, None),
        ("patch", "/api/v1/api-keys/{m}", wsh, {"usage_quota": 5}),
        ("delete", "/api/v1/api-keys/{m}", wsh, None),
        ("patch", "/api/v1/notifications/{m}", wsh, {"is_read": True}),
        ("delete", "/api/v1/notifications/{m}", wsh, None),
        ("get", "/api/v1/jobs/{m}", wsh, None),
        ("get", "/api/v1/jobs/runs/{m}", wsh, None),
        ("get", "/api/v1/jobs/runs/{m}/logs", wsh, None),
        ("get", "/api/v1/conversations/{m}", wsh, None),
        ("patch", "/api/v1/conversations/{m}", wsh, {"title": "Renamed"}),
        ("get", "/api/v1/conversations/{m}/messages", wsh, None),
        ("patch", "/api/v1/webhooks/subscriptions/{m}", wsh, {"active": True}),
        ("delete", "/api/v1/webhooks/subscriptions/{m}", wsh, None),
        ("get", "/api/v1/webhooks/subscriptions/{m}/deliveries", wsh, None),
        ("get", "/api/v1/webhooks/deliveries/{m}", wsh, None),
        ("get", "/api/v1/users/{m}/profile", auth, None),
        # Body-sourced id: `role_id` is a plain `str`, so pydantic does not
        # validate it and it reaches the same bind processor.
        (
            "post",
            "/api/v1/invitations",
            wsh,
            {"email": "inv@example.com", "role_id": MALFORMED},
        ),
    ]
    for method, url, headers, body in cases:
        resp = await app_client.request(
            method, url.replace("{m}", MALFORMED), headers=headers, json=body
        )
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)


async def test_malformed_id_returns_404_on_admin_routes(app_client):
    await register_user(app_client, "root@example.com")  # SUPERADMIN_EMAIL
    admin = auth_headers(await login(app_client, "root@example.com"))
    cases = [
        ("get", "/api/v1/admin/users/{m}", None),
        ("patch", "/api/v1/admin/users/{m}", {"is_active": False}),
        ("patch", "/api/v1/admin/workspaces/{m}/flags", {"flags": {}}),
    ]
    for method, url, body in cases:
        resp = await app_client.request(
            method, url.replace("{m}", MALFORMED), headers=admin, json=body
        )
        assert resp.status_code == 404, (method, url, resp.status_code, resp.text)


async def test_unknown_id_returns_the_same_404(app_client, owner):
    """A well-formed id matching nothing must be indistinguishable.

    Otherwise a caller can tell a malformed id from an unknown one and use the
    difference to probe which ids parse.
    """
    _, wsh = owner
    for url in [
        "/api/v1/workspaces/{m}",
        "/api/v1/roles/{m}",
        "/api/v1/conversations/{m}",
    ]:
        malformed = await app_client.get(url.replace("{m}", MALFORMED), headers=wsh)
        unknown = await app_client.get(url.replace("{m}", str(uuid.uuid4())), headers=wsh)
        assert malformed.status_code == unknown.status_code == 404, url


def test_malformed_uuid_error_is_recognised():
    """The failure the bind processor actually raises must be classified."""
    with pytest.raises(ValueError) as exc:
        uuid.UUID(MALFORMED)
    wrapped = StatementError("(builtins.ValueError)", "SELECT 1", {}, exc.value)
    assert is_malformed_uuid_error(wrapped) is True


@pytest.mark.parametrize(
    "value",
    ["not-a-uuid", "123", "", "not-a-uuid/../etc", "0" * 31, "g" * 36],
)
def test_everything_uuid_rejects_is_matched(value: str):
    """Whatever `uuid.UUID` rejects, the matcher must classify as malformed."""
    with pytest.raises(ValueError) as exc:
        uuid.UUID(value)
    wrapped = StatementError("(builtins.ValueError)", "SELECT 1", {}, exc.value)
    assert is_malformed_uuid_error(wrapped) is True


def test_other_statement_errors_are_not_masked():
    """A database failure that is not a bad id must stay a 500.

    Business logic raises bare `ValueError`s and a `StatementError` can wrap
    unrelated errors; neither may be reported as a missing resource.
    """
    missing_table = StatementError(
        "(sqlite3.OperationalError)",
        "SELECT 1",
        {},
        sqlite3.OperationalError("no such table: users"),
    )
    assert is_malformed_uuid_error(missing_table) is False

    # Same exception type as the masked case, different message.
    unrelated_value_error = StatementError(
        "(builtins.ValueError)", "SELECT 1", {}, ValueError("invalid channel 'sms'")
    )
    assert is_malformed_uuid_error(unrelated_value_error) is False

    # A bare ValueError is never wrapped, so it cannot reach this handler.
    assert is_malformed_uuid_error(ValueError("badly formed hexadecimal UUID string")) is False  # type: ignore[arg-type]
