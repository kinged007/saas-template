"""Every paged list route must have a default ORDER BY (#449).

`apply_query` only emits ORDER BY when the client sends `sort[]`/`_sort`, so a
request without one reaches `stmt.offset(...).limit(...)` unordered and the page
boundaries are whatever the database happens to return. `api_keys.py` grew a
`_DEFAULT_ORDER`; this pins the same contract for the other six routes.

The tie groups are seeded with explicit stamps and an insertion order that
disagrees with the default order, so a rowid-ordered read (pre-fix) and the
`<ts> DESC, id DESC` read (post-fix) are distinguishable. Relying on
`func.now()` instead would leave the tie to chance. Two stamp groups, not one:
with a single group the leading term's direction is unasserted, because a
flipped leading term still reads back id-desc (#929).
"""

from datetime import UTC, datetime, timedelta

from src.db.session import SessionFactory
from src.models.core import Invitation, Notification
from src.models.jobs import JobDefinition, JobRun, JobRunStatus, JobTrigger
from src.models.webhook import WebhookSubscription
from src.models.workspace import Workspace, WorkspaceMember
from tests.conftest import (
    auth_headers,
    create_workspace,
    register_user,
    ws_headers,
)

# Ids ascend within each group, and so does rowid order, so inserting the groups
# in this order leaves them disagreeing with the id-DESC read a default order
# produces. The newer group carries the lower ids, so flipping the leading term
# changes the order instead of only reversing a run of ids.
_STAMP = datetime(2026, 1, 1, tzinfo=UTC)
_GROUPS = (
    ([f"00000000-0000-4000-8000-00000000000{i}" for i in (1, 2, 3)], _STAMP),
    ([f"00000000-0000-4000-8000-00000000001{i}" for i in (1, 2, 3)], _STAMP - timedelta(days=1)),
)


async def _seed(session, *rows) -> None:
    session.add_all(rows)
    await session.commit()


def _order(rows: list[dict], *, key: str, ts_key: str, desc: bool) -> list[str]:
    """Ids a `<ts> <dir>, id <dir>` read returns for these rows."""
    return [r[key] for r in sorted(rows, key=lambda r: (r[ts_key], r[key]), reverse=desc)]


def _assert_default_order(rows: list[dict], *, key: str, ts_key: str) -> list[str]:
    """Assert `ts_key` desc with `key` (an id) breaking ties, and return ids.

    The self-referential sort is the weaker half; the tie-group assertion is
    what makes it bite, since those groups come back rowid-ordered pre-fix.
    Fewer than two stamp groups would leave the leading term's direction
    unasserted, so that is rejected rather than passed over.
    """
    stamps = {r[ts_key] for r in rows}
    assert 1 < len(stamps) < len(rows), f"expected >1 {ts_key} group, got {len(stamps)}"
    assert [r[key] for r in rows] == _order(rows, key=key, ts_key=ts_key, desc=True)
    for ids, _ in _GROUPS:
        tied = [r[key] for r in rows if r[key] in ids]
        assert tied == sorted(tied, reverse=True), f"tie group not id-desc: {tied}"
    return [r[key] for r in rows]


async def _assert_client_sort_overrides(
    client, path, headers, *, key: str, ts_key: str, sort_key: str
) -> None:
    """An explicit client sort replaces the default order (#930).

    `DESC` is sent uppercase on purpose: `parse_query` normalizes the direction,
    so it must behave exactly like `desc`. Pre-fix the uppercase form takes the
    `else` branch and sorts ascending (#931). `asc` is the other half of #930:
    the two stamp groups make it disagree with the default desc read, so a
    route that ignored the client sort would fail here.

    The repeated dialect (`sort[]`/`order[]`) shares the parse and the
    normalization with the flat one; one uppercase case pins that spelling too
    (#964), so normalizing inside a single branch cannot regress it unnoticed.
    """
    for direction, desc in (("DESC", True), ("asc", False)):
        resp = await client.get(
            path, params={"_sort": sort_key, "_order": direction, "limit": 50}, headers=headers
        )
        assert resp.status_code == 200, resp.text
        rows = resp.json()
        expected = _order(rows, key=key, ts_key=ts_key, desc=desc)
        assert [r[key] for r in rows] == expected, f"{direction} read is not {expected}"

    resp = await client.get(
        path, params={"sort[]": sort_key, "order[]": "DESC", "limit": 50}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    expected = _order(rows, key=key, ts_key=ts_key, desc=True)
    assert [r[key] for r in rows] == expected, f"sort[]/order[] DESC read is not {expected}"


async def _assert_pages_partition(client, path, headers, ids, key="id") -> None:
    """One row per page must reproduce the unpaginated read: no repeat, no skip."""
    paged: list[str] = []
    for offset in range(len(ids)):
        resp = await client.get(path, params={"offset": offset, "limit": 1}, headers=headers)
        assert resp.status_code == 200, resp.text
        chunk = resp.json()
        assert len(chunk) == 1, (offset, chunk)
        paged.append(chunk[0][key])
    assert paged == ids


async def _role_id(client, headers, name: str) -> str:
    resp = await client.get("/api/v1/roles", headers=headers)
    assert resp.status_code == 200, resp.text
    return next(r for r in resp.json() if r["name"] == name)["id"]


async def _user_id(client, headers) -> str:
    resp = await client.get("/api/v1/auth/me", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


async def test_members_unsorted_defaults_to_created_at_desc(app_client):
    client = app_client
    owner = await register_user(client, "mila@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _role_id(client, headers, "viewer")
    user_id = await _user_id(client, headers)

    async with SessionFactory() as session:
        await _seed(
            session,
            *[
                WorkspaceMember(
                    id=i,
                    workspace_id=ws["id"],
                    user_id=user_id,
                    role_id=role_id,
                    status="active",
                    created_at=stamp,
                    updated_at=stamp,
                )
                for ids, stamp in _GROUPS
                for i in ids
            ],
        )

    resp = await client.get("/api/v1/members", params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    # The member payload exposes the membership timestamp as `joined_at`.
    ids = _assert_default_order(body, key="membership_id", ts_key="joined_at")
    await _assert_pages_partition(client, "/api/v1/members", headers, ids, "membership_id")
    await _assert_client_sort_overrides(
        client,
        "/api/v1/members",
        headers,
        key="membership_id",
        ts_key="joined_at",
        sort_key="created_at",
    )


async def test_invitations_unsorted_defaults_to_created_at_desc(app_client):
    client = app_client
    owner = await register_user(client, "nils@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    role_id = await _role_id(client, headers, "viewer")
    user_id = await _user_id(client, headers)

    async with SessionFactory() as session:
        await _seed(
            session,
            *[
                Invitation(
                    id=i,
                    workspace_id=ws["id"],
                    email=f"i{i[-8:]}@example.com",
                    role_id=role_id,
                    invited_by_user_id=user_id,
                    token=f"tok-{i}",
                    status="pending",
                    expires_at=_STAMP,
                    created_at=stamp,
                    updated_at=stamp,
                )
                for ids, stamp in _GROUPS
                for i in ids
            ],
        )

    resp = await client.get("/api/v1/invitations", params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    ids = _assert_default_order(resp.json(), key="id", ts_key="created_at")
    await _assert_pages_partition(client, "/api/v1/invitations", headers, ids)
    await _assert_client_sort_overrides(
        client,
        "/api/v1/invitations",
        headers,
        key="id",
        ts_key="created_at",
        sort_key="created_at",
    )


async def test_notifications_unsorted_defaults_to_created_at_desc(app_client):
    client = app_client
    owner = await register_user(client, "odelia@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    user_id = await _user_id(client, headers)

    async with SessionFactory() as session:
        await _seed(
            session,
            *[
                Notification(
                    id=i,
                    user_id=user_id,
                    workspace_id=ws["id"],
                    type="system",
                    title=f"n{i[-8:]}",
                    body=None,
                    payload={},
                    created_at=stamp,
                    updated_at=stamp,
                )
                for ids, stamp in _GROUPS
                for i in ids
            ],
        )

    resp = await client.get("/api/v1/notifications", params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    ids = _assert_default_order(resp.json(), key="id", ts_key="created_at")
    await _assert_pages_partition(client, "/api/v1/notifications", headers, ids)
    await _assert_client_sort_overrides(
        client,
        "/api/v1/notifications",
        headers,
        key="id",
        ts_key="created_at",
        sort_key="created_at",
    )


async def test_job_runs_unsorted_defaults_to_scheduled_at_desc(app_client):
    """JobRun.created_at is not in _RUN_SORTABLE, so the default leads on
    scheduled_at — the column JobDetailPage already sorts on."""
    client = app_client
    owner = await register_user(client, "pieter@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])

    async with SessionFactory() as session:
        definition = JobDefinition(
            key="tie-order",
            workspace_id=ws["id"],
            name="tie",
            description="",
            cron_schedule="0 0 * * *",
            params_schema={},
            params={},
            enabled=False,
            timeout_seconds=60,
            created_at=_STAMP,
            updated_at=_STAMP,
        )
        session.add(definition)
        await session.commit()
        definition_id = definition.id
        await _seed(
            session,
            *[
                JobRun(
                    id=i,
                    definition_id=definition_id,
                    workspace_id=ws["id"],
                    status=JobRunStatus.SUCCESS.value,
                    trigger=JobTrigger.SCHEDULED.value,
                    params={},
                    scheduled_at=stamp,
                    created_at=stamp,
                    updated_at=stamp,
                )
                for ids, stamp in _GROUPS
                for i in ids
            ],
        )

    path = f"/api/v1/jobs/{definition_id}/runs"
    resp = await client.get(path, params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    ids = _assert_default_order(resp.json(), key="id", ts_key="scheduled_at")
    await _assert_pages_partition(client, path, headers, ids)
    await _assert_client_sort_overrides(
        client,
        path,
        headers,
        key="id",
        ts_key="scheduled_at",
        sort_key="scheduled_at",
    )


async def test_workspaces_unsorted_defaults_to_created_at_desc(app_client):
    client = app_client
    owner = await register_user(client, "quinn@example.com")
    ws = await create_workspace(client, owner)
    headers = auth_headers(owner)
    user_id = await _user_id(client, headers)
    role_id = await _role_id(client, ws_headers(owner, ws["id"]), "owner")

    async with SessionFactory() as session:
        spaces = [
            Workspace(
                id=i,
                name=f"W{i[-8:]}",
                slug=f"tie-{i[-8:]}",
                description=None,
                created_by_user_id=user_id,
                flags={},
                created_at=stamp,
                updated_at=stamp,
            )
            for ids, stamp in _GROUPS
            for i in ids
        ]
        await _seed(
            session,
            *spaces,
            *[
                WorkspaceMember(
                    workspace_id=s.id,
                    user_id=user_id,
                    role_id=role_id,
                    status="active",
                    created_at=s.created_at,
                    updated_at=s.updated_at,
                )
                for s in spaces
            ],
        )

    resp = await client.get("/api/v1/workspaces", params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    ids = _assert_default_order(resp.json(), key="id", ts_key="created_at")
    await _assert_pages_partition(client, "/api/v1/workspaces", headers, ids)
    await _assert_client_sort_overrides(
        client,
        "/api/v1/workspaces",
        headers,
        key="id",
        ts_key="created_at",
        sort_key="created_at",
    )


async def test_webhook_subscriptions_unsorted_defaults_to_created_at_desc(app_client):
    client = app_client
    owner = await register_user(client, "rufus@example.com")
    ws = await create_workspace(client, owner)
    headers = ws_headers(owner, ws["id"])
    user_id = await _user_id(client, headers)

    async with SessionFactory() as session:
        await _seed(
            session,
            *[
                WebhookSubscription(
                    id=i,
                    workspace_id=ws["id"],
                    url=f"https://example.com/{i[-8:]}",
                    events=[],
                    active=True,
                    created_by_user_id=user_id,
                    created_at=stamp,
                    updated_at=stamp,
                )
                for ids, stamp in _GROUPS
                for i in ids
            ],
        )

    path = "/api/v1/webhooks/subscriptions"
    resp = await client.get(path, params={"limit": 10}, headers=headers)
    assert resp.status_code == 200, resp.text
    ids = _assert_default_order(resp.json(), key="id", ts_key="created_at")
    await _assert_pages_partition(client, path, headers, ids)
    await _assert_client_sort_overrides(
        client,
        path,
        headers,
        key="id",
        ts_key="created_at",
        sort_key="created_at",
    )
