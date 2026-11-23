"""Malformed path ids are 422 on framework-validated UUID params and 404
elsewhere; well-formed but unknown ids are always 404.

`StringUUID.process_bind_param` (`src/db/base.py`) parses the id while
SQLAlchemy binds it, so an unparseable id raises before any route-level
`except` can see it. `src/api/errors.py` maps that one failure to 404.

These cases run through the real app, so the handler is exercised the way it
runs in production. `test_unrelated_db_error_stays_500` covers the other
direction: a database failure that is not a bad id must not be masked.
"""

from __future__ import annotations

import sqlite3
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import StatementError

from src.api.errors import is_malformed_uuid_error
from src.db.base import MalformedUUIDError, StringUUID
from tests.conftest import auth_headers, create_workspace, login, register_user, ws_headers

MALFORMED = "not-a-uuid"
# Same length as a real id, one non-hex digit: the failure mode a typo produces.
NON_HEX = "12345678-1234-1234-1234-1234567890zz"

# Route class split: params the framework validates as UUID (FastAPI rejects an
# unparseable value with 422 before any lookup runs) vs params looked up as
# strings (the bind-time 404 handler answers). A future `uuid.UUID`-annotated
# path param belongs in this set with a 422 expectation.
FRAMEWORK_VALIDATED_UUID_ROUTES = frozenset(
    {
        ("get", "/api/v1/workspaces/{m}"),
        ("patch", "/api/v1/workspaces/{m}"),
        ("delete", "/api/v1/workspaces/{m}"),
        ("delete", "/api/v1/workspaces/{m}/membership"),
        ("patch", "/api/v1/admin/workspaces/{m}/flags"),
    }
)


class _SQLiteDialect:
    """`process_bind_param` only reads `dialect.name`."""

    name = "sqlite"


def bind_error(value: str) -> StatementError:
    """The StatementError SQLAlchemy produces when `value` is bound."""
    with pytest.raises(MalformedUUIDError) as raised:
        StringUUID().process_bind_param(value, _SQLiteDialect())
    return StatementError("(builtins.ValueError)", "SELECT 1", {}, raised.value)


@pytest.fixture
async def owner(app_client):
    """An owner with a workspace, plus plain and workspace-scoped headers."""
    tokens = await register_user(app_client, "owner@example.com")
    workspace = await create_workspace(app_client, tokens, "Acme")
    return auth_headers(tokens), ws_headers(tokens, workspace["id"])


async def test_malformed_id_status_on_every_route(app_client, owner):
    auth, wsh = owner
    # `own_detail` is the route's own 404 for an id that matches nothing.
    # Base guards those ids with `uuid.UUID` before the bind
    # (`services/webhooks.py`, `uuid_or_404` in `api/deps.py`), so a malformed
    # id answers with that detail instead of the handler's — same as the admin
    # routes below. The pinned property is the status: never a 500.
    cases = [
        ("get", "/api/v1/workspaces/{m}", wsh, None, None),
        ("patch", "/api/v1/workspaces/{m}", wsh, {"name": "Renamed"}, None),
        ("delete", "/api/v1/workspaces/{m}", wsh, None, None),
        ("delete", "/api/v1/workspaces/{m}/membership", wsh, None, None),
        ("get", "/api/v1/roles/{m}", wsh, None, None),
        ("patch", "/api/v1/roles/{m}", wsh, {"name": "Renamed"}, None),
        ("patch", "/api/v1/members/{m}", wsh, {"role_id": str(uuid.uuid4())}, None),
        ("delete", "/api/v1/members/{m}", wsh, None, None),
        ("delete", "/api/v1/invitations/{m}", wsh, None, None),
        ("post", "/api/v1/invitations/{m}/decline", wsh, None, None),
        ("patch", "/api/v1/api-keys/{m}", wsh, {"usage_quota": 5}, None),
        ("delete", "/api/v1/api-keys/{m}", wsh, None, None),
        ("patch", "/api/v1/notifications/{m}", wsh, {"is_read": True}, None),
        ("delete", "/api/v1/notifications/{m}", wsh, None, None),
        ("get", "/api/v1/jobs/{m}", wsh, None, None),
        ("get", "/api/v1/jobs/runs/{m}", wsh, None, None),
        ("get", "/api/v1/jobs/runs/{m}/logs", wsh, None, None),
        ("get", "/api/v1/conversations/{m}", wsh, None, None),
        ("patch", "/api/v1/conversations/{m}", wsh, {"title": "Renamed"}, None),
        ("get", "/api/v1/conversations/{m}/messages", wsh, None, None),
        (
            "patch",
            "/api/v1/webhooks/subscriptions/{m}",
            wsh,
            {"active": True},
            "webhook subscription not found",
        ),
        (
            "delete",
            "/api/v1/webhooks/subscriptions/{m}",
            wsh,
            None,
            "webhook subscription not found",
        ),
        (
            "get",
            "/api/v1/webhooks/subscriptions/{m}/deliveries",
            wsh,
            None,
            "webhook subscription not found",
        ),
        (
            "get",
            "/api/v1/webhooks/deliveries/{m}",
            wsh,
            None,
            "webhook delivery not found",
        ),
        ("get", "/api/v1/users/{m}/profile", auth, None, "user not found"),
    ]
    for malformed in (MALFORMED, NON_HEX):
        for method, url, headers, body, own_detail in cases:
            resp = await app_client.request(
                method, url.replace("{m}", malformed), headers=headers, json=body
            )
            # Framework-validated UUID params answer 422 before any lookup;
            # string-then-look-up routes answer the bind-time 404.
            expected_status = 422 if (method, url) in FRAMEWORK_VALIDATED_UUID_ROUTES else 404
            assert resp.status_code == expected_status, (
                method,
                url,
                malformed,
                resp.status_code,
            )
            if expected_status == 404:
                # The body matters: several of these routes 404 on their own with a
                # different detail ("workspace not found"), and a status-only
                # assertion would pass for the wrong reason.
                expected = {"not found"} if own_detail is None else {"not found", own_detail}
                assert resp.json()["detail"] in expected, (
                    method,
                    url,
                    malformed,
                    resp.text,
                )


async def test_malformed_id_status_on_admin_routes(app_client):
    await register_user(app_client, "root@example.com")  # SUPERADMIN_EMAIL
    admin = auth_headers(await login(app_client, "root@example.com"))
    # Each of these routes looks its id up with `db.get` and owns a 404 detail
    # for an id that matches nothing ("user not found", "workspace not found").
    # String-param routes answer a malformed id with 404 (bind-time handler or
    # the route's own guard); the flags route's param is framework-validated
    # UUID, so it answers 422. The pinned property is the status: never a 500.
    cases = [
        ("get", "/api/v1/admin/users/{m}", None, "user not found"),
        ("patch", "/api/v1/admin/users/{m}", {"is_active": False}, "user not found"),
        ("patch", "/api/v1/admin/workspaces/{m}/flags", {"flags": {}}, "workspace not found"),
    ]
    for malformed in (MALFORMED, NON_HEX):
        for method, url, body, own_detail in cases:
            resp = await app_client.request(
                method, url.replace("{m}", malformed), headers=admin, json=body
            )
            expected_status = 422 if (method, url) in FRAMEWORK_VALIDATED_UUID_ROUTES else 404
            assert resp.status_code == expected_status, (
                method,
                url,
                malformed,
                resp.status_code,
            )
            if expected_status == 404:
                assert resp.json()["detail"] in {"not found", own_detail}, (
                    method,
                    url,
                    malformed,
                    resp.text,
                )


async def test_unknown_id_stays_404(app_client, owner):
    """A well-formed id matching nothing is always 404.

    A malformed id follows the route class: 422 on framework-validated UUID
    params, 404 on string-then-look-up routes. Only the status is compared: a
    lookup route answers an unknown id with its own 404 ("workspace not
    found"), and the pinned property is that neither status is a 500.
    """
    _, wsh = owner
    for url in [
        "/api/v1/workspaces/{m}",
        "/api/v1/roles/{m}",
        "/api/v1/conversations/{m}",
    ]:
        for malformed in (MALFORMED, NON_HEX):
            bad = await app_client.get(url.replace("{m}", malformed), headers=wsh)
            unknown = await app_client.get(url.replace("{m}", str(uuid.uuid4())), headers=wsh)
            assert unknown.status_code == 404, url
            expected_bad = 422 if ("get", url) in FRAMEWORK_VALIDATED_UUID_ROUTES else 404
            assert bad.status_code == expected_bad, (url, malformed, bad.status_code)


async def test_body_sourced_role_id_is_a_request_error(app_client, owner):
    """A body-sourced id is validated, not looked up: 422, one status per field.

    `role_id` is a pydantic `UUID`, so both invitation create and member role
    update answer 422 before any bind. 400 stays reserved for a well-formed role
    id that does not exist, so the response never reveals which it was.
    """
    _, wsh = owner
    unknown_role = str(uuid.uuid4())
    for method, url, body, expected in [
        (
            "post",
            "/api/v1/invitations",
            {"email": "inv@example.com", "role_id": MALFORMED},
            422,
        ),
        (
            "post",
            "/api/v1/invitations",
            {"email": "inv@example.com", "role_id": unknown_role},
            400,
        ),
        ("patch", "/api/v1/members/{m}", {"role_id": MALFORMED}, 422),
    ]:
        resp = await app_client.request(
            method,
            url.replace("{m}", unknown_role) if "{m}" in url else url,
            headers=wsh,
            json=body,
        )
        assert resp.status_code == expected, (method, url, body, resp.status_code, resp.text)


async def test_unrelated_db_error_stays_500(app):
    """A database failure that is not a bad id must re-raise as a 500.

    Drives a `StatementError` with a driver error as `orig` through the real app,
    so the handler's re-raise path is covered at the HTTP boundary. The route is
    local to the test: the thing under test is the handler, not the route.
    """

    @app.get("/__test__/db-error")
    async def _boom() -> None:
        raise StatementError(
            "(sqlite3.OperationalError)",
            "SELECT 1",
            {},
            sqlite3.OperationalError("no such table: workspaces"),
        )

    # raise_app_exceptions=False is what a real client sees: Starlette turns the
    # handler's re-raise into 500 instead of propagating it to the transport.
    transport = ASGITransport(app=app, raise_app_exceptions=False)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/__test__/db-error")
    assert resp.status_code == 500, (resp.status_code, resp.text)


@pytest.mark.parametrize(
    "value",
    [
        "not-a-uuid",
        "12345678-1234-1234-1234-1234567890zz",  # right length, non-hex digit
        "gggggggg-gggg-gggg-gggg-gggggggggggg",  # right length, non-hex letters
        "123",
        "",
        "not-a-uuid/../etc",
        "0" * 31,
        "g" * 36,
    ],
)
def test_everything_uuid_rejects_is_matched(value: str):
    """Whatever `uuid.UUID` rejects, the bind processor must type as malformed."""
    wrapped = bind_error(value)
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

    # A ValueError is the base of MalformedUUIDError, so only the type match counts.
    unrelated_value_error = StatementError(
        "(builtins.ValueError)", "SELECT 1", {}, ValueError("invalid channel 'sms'")
    )
    assert is_malformed_uuid_error(unrelated_value_error) is False

    # A bare ValueError is never wrapped, so it cannot reach this handler.
    assert is_malformed_uuid_error(ValueError("not a statement error")) is False  # type: ignore[arg-type]
