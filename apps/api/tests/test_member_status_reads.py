"""Every membership read decides from the member-status table, not a literal.

The repo-wide sweep (#978) replaced twelve `WorkspaceMember.status == "active"`
comparisons across six modules. No legal status distinguishes the table from the
literal, so `test_non_active_status_is_excluded_at_every_read` is a regression
net that passes before and after the change: it pins the behaviour each site
must keep, so the table cannot be widened or flipped to all-`False` unnoticed.
The two tests that do distinguish it pin the table itself and keep the literal
from coming back.
"""

from __future__ import annotations

import asyncio
import inspect
import re
from pathlib import Path

import pytest
from sqlalchemy import func, select

from src.db.session import SessionFactory
from src.models.core import Notification
from tests.conftest import auth_headers, create_workspace, register_user, ws_headers

# Same literal the sweep removed, matched so a later PR cannot reintroduce it.
_OPEN_STATUS_COMPARISON = re.compile(r"WorkspaceMember\.status\s*[!=]=\s*['\"]active['\"]")

SRC_ROOT = Path(__file__).resolve().parents[1] / "src"

# Set by the test before any helper reads it, so `_set_member_status` does not
# have to thread the workspace through every call.
_WS_ID = [None]


@pytest.fixture
def ws_slot():
    """Hand the test the list `_set_member_status` reads, and put its entry back
    when the test ends, so a failed assert cannot leak the id into the next one.
    """
    original = _WS_ID[0]
    yield _WS_ID
    _WS_ID[0] = original


async def _user_id(email: str) -> str:
    from src.models.workspace import User

    async with SessionFactory() as session:
        return (await session.execute(select(User).where(User.email == email))).scalar_one().id


async def _set_member_status(email: str, status: str) -> None:
    """Put a workspace member's row into `status`.

    No API writes `invited`, and suspending goes through a manager action, so
    the row is set directly.
    """
    from src.models.workspace import User, WorkspaceMember

    async with SessionFactory() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        member = (
            await session.execute(
                select(WorkspaceMember).where(
                    WorkspaceMember.workspace_id == _WS_ID[0], WorkspaceMember.user_id == user.id
                )
            )
        ).scalar_one()
        member.status = status
        await session.commit()


async def _count_notifications(user_id: str, type: str) -> int:
    async with SessionFactory() as session:
        result = await session.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.user_id == user_id, Notification.type == type)
        )
        return result.scalar_one()


async def _count_ge(user_id: str, type: str, expected: int) -> bool:
    return await _count_notifications(user_id, type) >= expected


async def _wait_for(predicate, timeout_secs: float = 3.0, interval: float = 0.02) -> bool:
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout_secs
    while loop.time() < deadline:
        result = predicate()
        if inspect.isawaitable(result):
            result = await result
        if result:
            return True
        await asyncio.sleep(interval)
    return False


async def _invite(client, owner_tokens, ws, email: str, role_name: str = "viewer") -> str:
    roles = await client.get("/api/v1/roles", headers=ws_headers(owner_tokens, ws["id"]))
    role_id = next(r["id"] for r in roles.json() if r["name"] == role_name)
    resp = await client.post(
        "/api/v1/invitations",
        json={"email": email, "role_id": role_id},
        headers=ws_headers(owner_tokens, ws["id"]),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["token"]


async def _join(client, tokens, token: str) -> None:
    resp = await client.post(
        f"/api/v1/invitations/accept?token={token}",
        headers={"Authorization": f"Bearer {tokens['access_token']}"},
    )
    assert resp.status_code == 200, resp.text


def test_active_membership_decides_every_member_status():
    """A status the domain gains is refused until this table decides it."""
    from src.models.workspace import ACTIVE_MEMBERSHIP_STATUSES, READS_AS_ACTIVE, MemberStatus

    assert set(READS_AS_ACTIVE) == {status.value for status in MemberStatus}
    assert READS_AS_ACTIVE == {
        MemberStatus.ACTIVE.value: True,
        MemberStatus.INVITED.value: False,
        MemberStatus.SUSPENDED.value: False,
    }
    assert ACTIVE_MEMBERSHIP_STATUSES == (MemberStatus.ACTIVE.value,)


def test_no_open_member_status_comparison_remains():
    """The literal is gone from `src/`, so no read decides it silently again."""
    offenders = [
        f"{path.relative_to(SRC_ROOT.parent)}:{lineno}"
        for path in sorted(SRC_ROOT.rglob("*.py"))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
        if _OPEN_STATUS_COMPARISON.search(line) and not line.lstrip().startswith("#")
    ]
    assert offenders == [], f"member status compared against a bare literal at {offenders}"


async def test_non_active_status_is_excluded_at_every_read(app_client, ws_slot):
    """Both non-active statuses lose every membership read; `active` keeps them.

    One assertion per swept site, so a site that stops consulting the table, or a
    table flipped to all-`False`, fails here.
    """
    client = app_client
    owner = await register_user(client, "reads-owner@example.com")
    ws = await create_workspace(client, owner)
    ws_slot[0] = ws["id"]
    peer = await register_user(client, "reads-peer@example.com")
    await _join(client, peer, await _invite(client, owner, ws, "reads-peer@example.com"))
    target = await register_user(client, "reads-target@example.com")
    await _join(client, target, await _invite(client, owner, ws, "reads-target@example.com"))
    peer_id = await _user_id("reads-peer@example.com")
    target_id = await _user_id("reads-target@example.com")

    for status in ("suspended", "invited"):
        await _set_member_status("reads-target@example.com", status)
        label = f"status={status}"

        # services/workspaces.py list_workspaces + api/routes/workspaces.py list filter.
        listed = await client.get("/api/v1/workspaces", headers=auth_headers(target))
        assert listed.status_code == 200, listed.text
        assert ws["id"] not in {w["id"] for w in listed.json()}, label

        me = await client.get("/api/v1/auth/me", headers=auth_headers(target))
        assert ws["id"] not in {w["id"] for w in me.json()["workspaces"]}, label

        # services/search_export.py member search hits.
        found = await client.get(
            "/api/v1/workspaces/search",
            params={"q": "reads-target"},
            headers=ws_headers(owner, ws["id"]),
        )
        assert found.status_code == 200, found.text
        hits = {r["id"] for r in found.json()["results"] if r["type"] == "member"}
        assert target_id not in hits, label

        # services/profiles.py co-membership visibility.
        peer_view = await client.get(
            f"/api/v1/users/{target_id}/profile", headers=auth_headers(peer)
        )
        assert peer_view.status_code == 404, f"{label}: {peer_view.text}"

        # services/profiles.py own export bundle.
        export = await client.get("/api/v1/me/export", headers=auth_headers(target))
        assert export.status_code == 200, export.text
        assert ws["id"] not in {w["workspace_id"] for w in export.json()["workspaces"]}, label

        # services/workspaces.py leave_workspace self-row lookup.
        left = await client.delete(
            f"/api/v1/workspaces/{ws['id']}/membership", headers=auth_headers(target)
        )
        assert left.status_code == 404, f"{label}: {left.text}"
        assert left.json()["detail"] == "membership not found", label

        # services/conversations.py _ensure_membership.
        talks = await client.get("/api/v1/conversations", headers=ws_headers(target, ws["id"]))
        assert talks.status_code == 403, f"{label}: {talks.text}"

        # services/conversations.py _require_active_members.
        with_target = await client.post(
            "/api/v1/conversations",
            json={
                "title": "Kickoff",
                "participant_user_ids": [peer_id, target_id],
                "initial_message": "hello",
            },
            headers=ws_headers(owner, ws["id"]),
        )
        assert with_target.status_code != 201, f"{label}: {with_target.text}"
        assert "not members" in with_target.json()["detail"], label

        # workflows member_joined fan-out: the target is not told about a later
        # join, the still-active peer is.
        late_email = f"reads-late-{status}@example.com"
        await _join(
            client,
            await register_user(client, late_email),
            await _invite(client, owner, ws, late_email),
        )
        peer_before = await _count_notifications(peer_id, "member_joined")
        target_before = await _count_notifications(target_id, "member_joined")
        # The peer is still active, so waiting for its notification proves the
        # bus ran before the target's absent one is read as "did not arrive".
        assert await _wait_for(
            lambda was=peer_before: _count_ge(peer_id, "member_joined", was + 1)
        ), f"{label}: peer never got member_joined"
        await asyncio.sleep(0.1)
        assert await _count_notifications(target_id, "member_joined") == target_before, label

    # The active peer still reads through everywhere the target was refused.
    peer_listed = await client.get("/api/v1/workspaces", headers=auth_headers(peer))
    assert ws["id"] in {w["id"] for w in peer_listed.json()}
    export = await client.get("/api/v1/me/export", headers=auth_headers(peer))
    assert ws["id"] in {w["workspace_id"] for w in export.json()["workspaces"]}
