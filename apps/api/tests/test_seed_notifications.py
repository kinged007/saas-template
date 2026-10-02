"""Issues #212, #378, #379, #381: seeded invitation notifications must carry payload["url"].

The real invite path (workflows.on_member_invited) sets ``url`` to
``src.core.routes.INVITATIONS_ROUTE`` in the notification payload, and
NotificationCenter renders its "Open" button only when that key is present.
The dev seed built the same payload without it, so the bell entries in the
seeded demo were dead ends. This asserts the seed's persisted payload matches
the workflow's.

``INVITATIONS_ROUTE`` is a static frontend route, so every seeded
``workspace_invitation`` row gets it — not only the ones backed by a live
pending invitation. ``invitation_id`` / ``invited_by`` stay gated on a real
invitation row, since those describe an invite that actually exists.

Re-running the seed adds no notification rows. That is scoped to the
notifications this file reads; the test does not assert idempotency for the
other tables the seed writes.
"""

import pytest
from sqlalchemy import select

from src.core.routes import INVITATIONS_ROUTE
from src.db.session import SessionFactory
from src.models.core import Invitation, Notification
from src.settings import settings


def _assert_carries_url(n: Notification) -> None:
    """Assert one invitation notification carries the frontend route.

    A NULL payload counts as an empty one: it is the defect this test exists for
    (the bell Open button renders only from ``payload.url``), so it must fail the
    assertion with the message instead of raising ``AttributeError`` (#583).
    """
    assert (n.payload or {}).get("url") == INVITATIONS_ROUTE, (
        f"seeded invitation notification {n.title!r} is missing payload.url; "
        "the bell Open button will not render"
    )


def test_seed_and_workflow_share_one_route_constant():
    """The seed must take the route from the workflow, not repeat it (#377)."""
    from src import seed

    assert seed.INVITATIONS_ROUTE is INVITATIONS_ROUTE


async def test_seed_invitation_notifications_carry_url(monkeypatch):
    from src.seed import _notifications
    from src.seed import main as seed_main

    # The exact-count assertions below hold only in default mode; the flag is
    # env-driven, so pin it rather than depend on the runner's environment.
    monkeypatch.setattr(settings, "single_workspace", False)

    await seed_main()

    async with SessionFactory() as session:
        rows = (await session.execute(select(Notification))).scalars().all()
        pending_q = select(Invitation.id).where(Invitation.status == "pending")
        pending = set((await session.execute(pending_q)).scalars().all())

    # One notification per fixture row. "at least one" would still pass while a
    # defect drops the rest (#586).
    assert len(rows) == len(_notifications()), (
        f"the seed must create one notification per fixture row: "
        f"{len(_notifications())} fixture rows -> {len(rows)} notifications"
    )

    invitations = [n for n in rows if n.type == "workspace_invitation"]
    assert invitations, "seed should create workspace_invitation notifications"

    for n in invitations:
        _assert_carries_url(n)

    # Only rows backed by a real pending invitation carry the invite id, one
    # link per notification. The resolve check runs before distinctness: a
    # dangling id is the worse defect, and the distinctness failure would
    # otherwise report in its place (#581).
    with_invite = [
        n.payload["invitation_id"] for n in invitations if (n.payload or {}).get("invitation_id")
    ]
    assert set(with_invite) == pending, (
        f"every pending invitation must be linked and every link must resolve; "
        f"unlinked: {sorted(pending - set(with_invite))}, "
        f"dangling: {sorted(set(with_invite) - pending)}"
    )
    assert len(with_invite) == len(set(with_invite)), (
        f"each notification should link to a distinct invitation, got {sorted(with_invite)}"
    )

    await seed_main()

    async with SessionFactory() as session:
        after = len((await session.execute(select(Notification.id))).scalars().all())
    assert after == len(rows), (
        f"re-running the seed must add no notifications: {len(rows)} -> {after}"
    )


def test_null_payload_reports_the_defect():
    """A NULL payload fails the assertion; it does not error out (#583)."""
    n = Notification(
        id="n1",
        user_id="u1",
        workspace_id="w1",
        type="workspace_invitation",
        title="New invitation sent",
        payload=None,
    )

    with pytest.raises(AssertionError, match=r"missing payload\.url"):
        _assert_carries_url(n)
