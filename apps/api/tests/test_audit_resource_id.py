"""Audit resource_id is UUID-bound on Postgres: sentinel strings crashed writes.

`audit_log_entries.resource_id` is a native UUID on Postgres, and the model
binds it as one — so a non-UUID value fails the write before any SQL runs
(SQLite is loosely typed and never noticed). Bulk acknowledge used the
sentinel "all"; it now files under the workspace instead.
"""

import asyncio

from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.audit import AuditLogEntry
from src.services.audit import AuditService
from tests.conftest import auth_headers, create_workspace, register_user, ws_headers


async def _wait_for_audit(resource_id: str, action: str, timeout_s: float = 10.0):
    for _ in range(int(timeout_s * 10)):
        async with SessionFactory() as session:
            entry = (
                await session.execute(
                    select(AuditLogEntry).where(
                        AuditLogEntry.resource_id == resource_id,
                        AuditLogEntry.action == action,
                    )
                )
            ).scalar_one_or_none()
            if entry is not None:
                return entry
        await asyncio.sleep(0.1)
    raise AssertionError(f"no {action} audit entry for {resource_id}")


async def test_bulk_acknowledge_audits_workspace_scope(app_client):
    """The bulk-ack entry's resource is the workspace, not the string "all"."""
    client = app_client
    owner = await register_user(client, "ack-owner@example.com")
    ws = await create_workspace(client, owner)
    invitee = await register_user(client, "ack-member@example.com")
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner, ws["id"]))
    viewer = next(r for r in roles.json() if r["name"] == "viewer")
    invite = await client.post(
        "/api/v1/invitations",
        json={"email": "ack-member@example.com", "role_id": viewer["id"]},
        headers=ws_headers(owner, ws["id"]),
    )
    await client.post(
        "/api/v1/invitations/accept",
        params={"token": invite.json()["token"]},
        headers=auth_headers(invitee),
    )
    member_headers = ws_headers(invitee, ws["id"])

    resp = await client.patch("/api/v1/notifications/read-all", headers=member_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["acknowledged"] >= 1

    entry = await _wait_for_audit(ws["id"], "notifications.acknowledged")
    assert entry.workspace_id == ws["id"]
    assert entry.resource_type == "notification"


async def test_non_uuid_resource_id_skips_dedupe_without_raising():
    """Legacy sentinel rows must never break the lookup: without a UUID there
    is no dedupe key to check, so it is skipped. (New writes can never carry
    one — the model bind rejects non-UUIDs, so sentinels have to be fixed at
    their call site, as bulk-acknowledge was above.)"""
    import pytest
    from sqlalchemy.exc import StatementError

    async with SessionFactory() as session:
        service = AuditService(session)
        assert (
            await service._find_by_source_event(
                "ws", "notification", "all", "notifications.acknowledged", "evt-1"
            )
        ) is None
        with pytest.raises(StatementError):
            await service.record(
                workspace_id="ws",
                resource_type="notification",
                resource_id="all",
                action="notifications.acknowledged",
                actor_user_id="u",
                details={"count": 1},
                source_event_id="evt-1",
            )
