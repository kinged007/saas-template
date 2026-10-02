"""Issue #212: seeded invitation notifications must carry payload["url"].

The real invite path (workflows.on_member_invited) sets ``url`` to
``src.workflows.INVITATIONS_ROUTE`` in the notification payload, and
NotificationCenter renders its "Open" button only when that key is present.
The dev seed built the same payload without it, so the bell entries in the
seeded demo were dead ends. This asserts the seed's persisted payload matches
the workflow's.

``INVITATIONS_ROUTE`` is a static frontend route, so every seeded
``workspace_invitation`` row gets it — not only the ones backed by a live
pending invitation. ``invitation_id`` / ``invited_by`` stay gated on a real
invitation row, since those describe an invite that actually exists.

Re-running the seed adds nothing: the seed is idempotent.
"""

from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.core import Invitation, Notification
from src.workflows import INVITATIONS_ROUTE


def test_seed_and_workflow_share_one_route_constant():
    """The seed must take the route from the workflow, not repeat it (#377)."""
    from src import seed

    assert seed.INVITATIONS_ROUTE is INVITATIONS_ROUTE


async def test_seed_invitation_notifications_carry_url():
    from src.seed import _notifications
    from src.seed import main as seed_main

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
        assert n.payload.get("url") == INVITATIONS_ROUTE, (
            f"seeded invitation notification {n.title!r} is missing payload.url; "
            "the bell Open button will not render"
        )

    # Only rows backed by a real pending invitation carry the invite id, one
    # link per notification.
    with_invite = [
        n.payload["invitation_id"] for n in invitations if n.payload.get("invitation_id")
    ]
    assert len(with_invite) == len(set(with_invite)), (
        f"each notification should link to a distinct invitation, got {sorted(with_invite)}"
    )
    assert set(with_invite) == pending, (
        f"every pending invitation must be linked and every link must resolve; "
        f"unlinked: {sorted(pending - set(with_invite))}, "
        f"dangling: {sorted(set(with_invite) - pending)}"
    )

    await seed_main()

    async with SessionFactory() as session:
        after = len((await session.execute(select(Notification.id))).scalars().all())
    assert after == len(rows), (
        f"re-running the seed must add no notifications: {len(rows)} -> {after}"
    )
