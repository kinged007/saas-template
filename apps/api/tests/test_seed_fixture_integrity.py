"""#586: a fixture row naming a slug or email the seed does not define must fail the seed.

The seed's per-run guards (``if slug not in workspaces: continue``) skip a slug
that is known but absent from this run — single-workspace mode and the
foreign-workspace case both depend on that. They also swallow a slug no fixture
defines at all, which is a typo in code a reviewer reads, and ``users[email]``
turns an undefined email into a bare ``KeyError`` naming neither the fixture nor
the row. Either way the demo ships with rows quietly missing.

``_check_fixtures`` separates the two cases and runs before any DB work, so a
bad row leaves no half-seeded database behind. The email check is narrower still:
it applies where the loop reads ``users[email]``, and ``INVITATIONS`` is exempt
because inviting an address that has not registered yet is the flow it exists to
demo.
"""

import pytest
from sqlalchemy import select

from src import seed
from src.db.session import SessionFactory
from src.models.core import Invitation, Notification
from src.models.workspace import Workspace
from src.seed import main as seed_main
from src.settings import settings

_NOTIFICATION = (
    "workspace_invitation",
    "You were invited to nowhere",
    "Nobody invited you to nowhere.",
    False,
    0,
)


def _with_notification(monkeypatch, *, email: str, slug: str) -> None:
    original = seed._notifications
    monkeypatch.setattr(
        seed, "_notifications", lambda: [*original(), (email, slug, *_NOTIFICATION)]
    )


async def test_seed_fails_on_unknown_notification_slug(monkeypatch):
    _with_notification(monkeypatch, email="admin@example.com", slug="typo-corp")

    with pytest.raises(
        RuntimeError, match="notifications fixture names unknown workspace slug 'typo-corp'"
    ):
        await seed_main()

    async with SessionFactory() as session:
        rows = (await session.execute(select(Workspace))).scalars().all()
    assert rows == [], "no workspace row was written"


async def test_seed_fails_on_unknown_notification_email(monkeypatch):
    _with_notification(monkeypatch, email="ghost@example.com", slug="acme-corp")

    with pytest.raises(
        RuntimeError, match="notifications fixture names unknown user email 'ghost@example.com'"
    ):
        await seed_main()


@pytest.mark.parametrize(
    ("fixture", "kind", "bad_row"),
    [
        ("MEMBERSHIPS", "workspace slug", ("typo-corp", "user1@example.com", "editor")),
        ("MEMBERSHIPS", "user email", ("acme-corp", "ghost@example.com", "editor")),
        ("INVITATIONS", "workspace slug", ("typo-corp", "user2@example.com", "viewer")),
        (
            "API_KEYS",
            "workspace slug",
            ("typo-corp", "user1@example.com", "typo", ["member:read"]),
        ),
        (
            "API_KEYS",
            "user email",
            ("acme-corp", "ghost@example.com", "typo", ["member:read"]),
        ),
    ],
)
async def test_seed_rejects_undefined_reference_in_every_fixture(
    monkeypatch, fixture, kind, bad_row
):
    monkeypatch.setattr(seed, fixture, [*getattr(seed, fixture), bad_row])
    # The message names the fixture the way the seed labels it ("api keys") and
    # the offending value, so a generic "bad fixture" string fails here.
    label = fixture.lower().replace("_", " ")
    value = bad_row[0] if kind == "workspace slug" else bad_row[1]

    with pytest.raises(RuntimeError, match=rf"{label} fixture names unknown {kind} {value!r}"):
        await seed_main()


async def test_invitation_to_an_unregistered_address_is_not_a_failure(monkeypatch):
    """``INVITATIONS`` may name an address the seed never registered.

    The loop invites the address as a string and reads only
    ``users["admin@example.com"]`` for the inviter, so an unregistered invitee is
    the accept-invitation flow, not a typo. An email check that covered this
    fixture would forbid the flow it exists to demo.
    """
    monkeypatch.setattr(
        seed, "INVITATIONS", [*seed.INVITATIONS, ("acme-corp", "newcomer@example.com", "viewer")]
    )

    await seed_main()

    async with SessionFactory() as session:
        rows = (await session.execute(select(Invitation.email))).scalars().all()
    assert "newcomer@example.com" in rows


async def test_single_workspace_slug_skip_is_not_a_failure(monkeypatch):
    """The skip guards stay for a slug that is known but not part of this run.

    Single-workspace mode puts only ``acme-corp`` in the run, so every
    ``globex`` row takes the skip path. Raising there would break every
    single-workspace seed, so the check must reject a slug the fixtures never
    define and nothing else.
    """
    monkeypatch.setattr(settings, "single_workspace", True)

    await seed_main()

    async with SessionFactory() as session:
        slugs = (await session.execute(select(Workspace.slug))).scalars().all()
        notifications = (await session.execute(select(Notification.id))).scalars().all()
    acme_notifications = sum(1 for _, slug, *_ in seed._notifications() if slug == "acme-corp")

    assert list(slugs) == ["acme-corp"], "globex rows must be skipped, not created"
    assert len(notifications) == acme_notifications, "the acme-corp rows must still land"
