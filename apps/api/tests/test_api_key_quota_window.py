"""Issue #69: API key quotas reset on a calendar-month window.

`usage_quota` caps the uses inside the current calendar month
(`usage_window_count`); `usage_count` stays the lifetime total.
"""

from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.session import engine
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


def test_roll_window_opens_the_window_on_first_use():
    key = ApiKey(usage_count=12, usage_window_count=0, usage_window_start=None)
    ApiKeyService.roll_window(key, now=datetime(2026, 3, 17, 12, 30, tzinfo=UTC))
    assert key.usage_window_count == 0
    assert key.usage_window_start == datetime(2026, 3, 1, tzinfo=UTC)
    assert key.usage_count == 12  # lifetime total untouched


def test_roll_window_ignores_later_days_of_the_same_month():
    key = ApiKey(
        usage_window_count=7,
        usage_window_start=datetime(2026, 3, 1, tzinfo=UTC),
    )
    ApiKeyService.roll_window(key, now=datetime(2026, 3, 31, 23, 59, tzinfo=UTC))
    assert key.usage_window_count == 7
    assert key.usage_window_start == datetime(2026, 3, 1, tzinfo=UTC)


def test_roll_window_keeps_the_count_when_now_precedes_the_stored_start():
    # A host whose clock steps backwards must not get a second full budget.
    key = ApiKey(
        usage_window_count=9,
        usage_window_start=datetime(2026, 3, 1, tzinfo=UTC),
    )
    ApiKeyService.roll_window(key, now=datetime(2026, 2, 15, tzinfo=UTC))
    assert key.usage_window_count == 9
    assert key.usage_window_start == datetime(2026, 3, 1, tzinfo=UTC)


def test_roll_window_rolls_across_month_and_year_boundaries():
    february = ApiKey(
        usage_window_count=7,
        usage_window_start=datetime(2026, 2, 1, tzinfo=UTC),
    )
    ApiKeyService.roll_window(february, now=datetime(2026, 3, 1, tzinfo=UTC))
    assert february.usage_window_count == 0
    assert february.usage_window_start == datetime(2026, 3, 1, tzinfo=UTC)

    december = ApiKey(
        usage_window_count=7,
        usage_window_start=datetime(2025, 12, 1, tzinfo=UTC),
    )
    ApiKeyService.roll_window(december, now=datetime(2026, 1, 15, tzinfo=UTC))
    assert december.usage_window_count == 0
    assert december.usage_window_start == datetime(2026, 1, 1, tzinfo=UTC)


def test_roll_window_reads_a_naive_window_start_as_utc():
    # SQLite hands back naive datetimes for DateTime(timezone=True) columns.
    stale = ApiKey(usage_window_count=7, usage_window_start=datetime(2026, 2, 1))
    ApiKeyService.roll_window(stale, now=datetime(2026, 3, 1, tzinfo=UTC))
    assert stale.usage_window_count == 0
    assert stale.usage_window_start == datetime(2026, 3, 1, tzinfo=UTC)

    current = ApiKey(usage_window_count=7, usage_window_start=datetime(2026, 3, 1))
    ApiKeyService.roll_window(current, now=datetime(2026, 3, 20, tzinfo=UTC))
    assert current.usage_window_count == 7
