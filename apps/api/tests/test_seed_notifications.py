"""Issue #212: seeded invitation notifications must carry payload["url"].

The real invite path (workflows.on_member_invited) sets
``url: "/invitations"`` in the notification payload, and NotificationCenter
renders its "Open" button only when that key is present. The dev seed built
the same payload without it, so the bell entries in the seeded demo were dead
ends. This asserts the seed's persisted payload matches the workflow's.

``/invitations`` is a static frontend route, so every seeded
``workspace_invitation`` row gets it — not only the ones backed by a live
pending invitation. ``invitation_id`` / ``invited_by`` stay gated on a real
invitation row, since those describe an invite that actually exists.
"""

from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.core import Notification


async def test_seed_invitation_notifications_carry_url(app_client):
    from src.seed import INVITATIONS
    from src.seed import main as seed_main

    await seed_main()

    async with SessionFactory() as session:
        rows = (await session.execute(select(Notification))).scalars().all()

    invitations = [n for n in rows if n.type == "workspace_invitation"]
    assert invitations, "seed should create workspace_invitation notifications"

    for n in invitations:
        assert n.payload.get("url") == "/invitations", (
            f"seeded invitation notification {n.title!r} is missing payload.url; "
            "the bell Open button will not render"
        )

    # Only rows backed by a real pending invitation carry the invite id.
    with_invite = [n for n in invitations if n.payload.get("invitation_id")]
    assert len(with_invite) == len(INVITATIONS), (
        f"expected one url+invitation_id row per seeded invitation "
        f"({len(INVITATIONS)}), got {len(with_invite)}"
    )
