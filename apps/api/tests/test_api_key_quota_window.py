"""Issue #69: API key quotas reset on a calendar-month window.

`usage_quota` caps the uses inside the current calendar month
(`usage_window_count`); `usage_count` stays the lifetime total.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import SessionFactory, engine
from src.models.api_key import ApiKey
from src.services.api_keys import ApiKeyService
from tests.conftest import create_workspace, register_user, ws_headers


async def _mint_key(
    client, headers: dict, *, name: str, permissions: list[str], quota: int
) -> dict:
    resp = await client.post(
        "/api/v1/api-keys",
        json={"name": name, "permissions": permissions, "usage_quota": quota},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _set_window_start(key_id: str, value: datetime) -> None:
    async with AsyncSession(engine) as db:
        key = await db.get(ApiKey, key_id)
        assert key is not None
        key.usage_window_start = value
        await db.commit()


async def _listed_key(client, headers: dict, key_id: str) -> dict:
    listing = (await client.get("/api/v1/api-keys", headers=headers)).json()
    return next(k for k in listing if k["id"] == key_id)


def _month_start(now: datetime) -> datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def _previous_month() -> datetime:
    """Aware UTC datetime in the month before now (never in the current one)."""
    return _month_start(datetime.now(UTC)) - timedelta(days=1)


def _next_month() -> datetime:
    return _month_start(_previous_month()) + timedelta(days=32)


async def test_quota_resets_on_the_first_use_in_a_new_calendar_month(app_client):
    client = app_client
    owner = await register_user(client, "month@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="monthly", permissions=["member:read"], quota=1)
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}

    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 403

    await _set_window_start(created["id"], _previous_month())

    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 200
    assert resp.headers["X-API-Key-Remaining"] == "0"

    item = await _listed_key(client, headers, created["id"])
    assert item["usage_window_count"] == 1
    assert item["usage_count"] == 2  # lifetime total is not reset
    # The field is documented as UTC, so it has to carry an offset: an
    # offset-less string is read as browser-local by the frontend's formatDate.
    window_start = datetime.fromisoformat(item["usage_window_start"])
    assert window_start.utcoffset() == timedelta(0)


async def test_no_rollover_inside_the_same_calendar_month(app_client):
    client = app_client
    owner = await register_user(client, "same-month@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="monthly", permissions=["member:read"], quota=1)
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    # window opened earlier this month, later in the same month → no reset
    await _set_window_start(created["id"], _month_start(datetime.now(UTC)))

    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()

    item = await _listed_key(client, headers, created["id"])
    assert item["usage_window_count"] == 1  # the 403 did not count
    assert item["usage_count"] == 1


async def test_rollover_also_runs_on_key_only_routes(app_client):
    client = app_client
    owner = await register_user(client, "key-only@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(
        client, headers, name="key-only", permissions=["notification:read"], quota=1
    )
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}

    assert (await client.get("/api/v1/notifications", headers=key_headers)).status_code == 200
    assert (await client.get("/api/v1/notifications", headers=key_headers)).status_code == 403

    await _set_window_start(created["id"], _previous_month())

    resp = await client.get("/api/v1/notifications", headers=key_headers)
    assert resp.status_code == 200
    assert (await _listed_key(client, headers, created["id"]))["usage_window_count"] == 1


async def test_quota_headers_report_the_current_window(app_client):
    client = app_client
    owner = await register_user(client, "headers@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(
        client, headers, name="windowed", permissions=["member:read"], quota=2
    )
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}

    first = await client.get("/api/v1/members", headers=key_headers)
    assert first.headers["X-API-Key-Quota"] == "2"
    assert first.headers["X-API-Key-Remaining"] == "1"
    second = await client.get("/api/v1/members", headers=key_headers)
    assert second.headers["X-API-Key-Remaining"] == "0"


async def test_window_reset_header_points_at_the_next_month_boundary(app_client):
    client = app_client
    owner = await register_user(client, "reset@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="reset", permissions=["member:read"], quota=2)
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}

    resp = await client.get("/api/v1/members", headers=key_headers)
    reset = parsedate_to_datetime(resp.headers["X-API-Key-Window-Reset"])
    assert reset > datetime.now(UTC)
    assert (reset.day, reset.hour, reset.minute) == (1, 0, 0)


async def test_quota_rejection_still_reports_the_budget(app_client):
    """A client blocked at the quota needs the budget and the reset time."""
    client = app_client
    owner = await register_user(client, "blocked@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="blocked", permissions=["member:read"], quota=1)
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 403
    assert "quota" in resp.json()["detail"].lower()
    assert resp.headers["X-API-Key-Quota"] == "1"
    assert resp.headers["X-API-Key-Remaining"] == "0"
    assert "X-API-Key-Window-Reset" in resp.headers


async def test_concurrent_requests_cannot_both_spend_the_last_unit(app_client):
    """The atomicity this PR exists for: accepted requests never exceed the
    quota, and the counter agrees with the accepted count."""
    client = app_client
    owner = await register_user(client, "race@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="racy", permissions=["member:read"], quota=3)
    raw = created["key"]

    # ponytail: sqlite serialises writers per statement, so this reproduces the
    # month-boundary clobber (N charges, one counted) and not every interleaving
    # a row-lock backend allows. Ceiling: no postgres run in CI.
    # Upgrade path: parametrise the suite over both backends.
    async def charge() -> bool:
        async with SessionFactory() as db:
            service = ApiKeyService(db)
            key = await service.authenticate(raw)
            assert key is not None
            return await service.record_use(key)

    accepted = sum(await asyncio.gather(*(charge() for _ in range(8))))
    assert accepted == 3

    async with SessionFactory() as db:
        key = await db.get(ApiKey, created["id"])
        assert key.usage_window_count == accepted
        assert key.usage_count == accepted


async def test_fail_closed_when_the_host_clock_steps_back(app_client):
    """A stored start later than `now` means the clock moved backwards. Rolling
    there would hand out a second full budget, so an exhausted key keeps its
    counter and stays rejected."""
    client = app_client
    owner = await register_user(client, "clock@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="clock", permissions=["member:read"], quota=1)
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    await _set_window_start(created["id"], _next_month())
    resp = await client.get("/api/v1/members", headers=key_headers)
    assert resp.status_code == 403

    item = await _listed_key(client, headers, created["id"])
    assert item["usage_window_count"] == 1  # not reset to a fresh budget
    assert item["usage_window_start"].startswith(_next_month().strftime("%Y-%m"))


async def test_rollover_crosses_the_year_boundary(app_client):
    client = app_client
    owner = await register_user(client, "year@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    created = await _mint_key(client, headers, name="year", permissions=["member:read"], quota=1)
    key_headers = {"Authorization": f"Bearer {created['key']}", "X-Workspace-ID": ws["id"]}
    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200

    last_december = _month_start(datetime.now(UTC)).replace(month=12)
    last_december = last_december.replace(year=last_december.year - 1)
    await _set_window_start(created["id"], last_december)

    assert (await client.get("/api/v1/members", headers=key_headers)).status_code == 200
    item = await _listed_key(client, headers, created["id"])
    assert item["usage_window_count"] == 1
    assert datetime.fromisoformat(item["usage_window_start"]) == _month_start(datetime.now(UTC))


def test_migration_0019_seeds_the_window_start_too():
    """The backfill must seed both columns.

    A NULL start reads as "no window has been opened yet", so the rollover
    zeroes the counter on the key's first request and the seed is discarded —
    the second full budget the migration exists to prevent.
    """
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "0019_api_key_quota_window.py"
    )
    spec = spec_from_file_location("migration_0019", path)
    module = module_from_spec(spec)
    spec.loader.exec_module(module)

    sqlite = sa.create_engine("sqlite://")
    try:
        with sqlite.begin() as conn:
            conn.execute(
                sa.text(
                    "CREATE TABLE api_keys"
                    " (id VARCHAR(36) PRIMARY KEY, usage_count INTEGER NOT NULL DEFAULT 0)"
                )
            )
            conn.execute(sa.text("INSERT INTO api_keys VALUES ('exhausted', 50), ('fresh', 0)"))
            with Operations.context(MigrationContext.configure(conn)):
                module.upgrade()
            rows = {
                row[0]: (row[1], row[2])
                for row in conn.execute(
                    sa.text("SELECT id, usage_window_count, usage_window_start FROM api_keys")
                )
            }
    finally:
        sqlite.dispose()

    now = datetime.now(UTC)
    assert rows["exhausted"][0] == 50  # seeded from the lifetime total
    start = datetime.fromisoformat(rows["exhausted"][1])
    assert (start.year, start.month, start.day) == (now.year, now.month, 1)
    assert rows["fresh"][0] == 0
    assert rows["fresh"][1] is not None
