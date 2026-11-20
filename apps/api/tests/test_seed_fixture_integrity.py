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

_NOTIFICATION = {
    "type": "workspace_invitation",
    "title": "You were invited to nowhere",
    "body": "Nobody invited you to nowhere.",
    "acknowledged": False,
    "age_hours": 0,
}

_GHOST_EMAIL = "ghost@example.com"


def _append_row(monkeypatch, attr: str, row) -> None:
    """Add one row to a fixture: a list constant, or the function that builds them."""
    if callable(getattr(seed, attr)):
        original = getattr(seed, attr)
        monkeypatch.setattr(seed, attr, lambda: [*original(), row])
    else:
        monkeypatch.setattr(seed, attr, [*getattr(seed, attr), row])


def _with_notification(monkeypatch, *, email: str, slug: str) -> None:
    _append_row(
        monkeypatch, "_notifications", seed.NotificationRow(slug=slug, email=email, **_NOTIFICATION)
    )


@pytest.mark.parametrize(
    ("fixture", "rows"),
    [
        ("MEMBERSHIPS", seed.MEMBERSHIPS),
        ("INVITATIONS", seed.INVITATIONS),
        ("API_KEYS", seed.API_KEYS),
        ("_notifications", seed._notifications()),
    ],
)
def test_every_fixture_row_names_its_slug_and_email(fixture, rows):
    """#914: the row shape is named, so a check reads ``row.slug`` / ``row.email``.

    Positionally unpacked tuples make a transposed row indistinguishable from
    a wrong one: the check reads the field it assumed and names it in the
    message. Named fields also pin every fixture to the same leading order, so
    #916's two-path destructuring cannot come back.
    """
    for row in rows:
        assert row.slug and row.email, f"{fixture} row {row!r} has an empty slug or email"
        assert row._fields[:2] == ("slug", "email"), (
            f"{fixture} row {row!r} does not start with (slug, email)"
        )


async def test_transposed_row_names_the_field_it_carries(monkeypatch):
    """The message must point at the offending row, not just the assumed field.

    Both strings are valid demo values, so only the row itself shows that the
    two were swapped; a message naming the value alone sends the reader
    looking for a typo in the wrong field.
    """
    transposed = seed.MembershipRow(slug="user1@example.com", email="acme-corp", role="editor")
    monkeypatch.setattr(seed, "MEMBERSHIPS", [*seed.MEMBERSHIPS, transposed])

    with pytest.raises(RuntimeError) as excinfo:
        await seed_main()

    message = str(excinfo.value)
    assert "memberships fixture names unknown workspace slug" in message
    assert repr(transposed) in message, "the message must carry the offending row"


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
        (
            "MEMBERSHIPS",
            "workspace slug",
            seed.MembershipRow(slug="typo-corp", email="user1@example.com", role="editor"),
        ),
        (
            "MEMBERSHIPS",
            "user email",
            seed.MembershipRow(slug="acme-corp", email=_GHOST_EMAIL, role="editor"),
        ),
        (
            "INVITATIONS",
            "workspace slug",
            seed.InvitationRow(slug="typo-corp", email="user2@example.com", role="viewer"),
        ),
        (
            "API_KEYS",
            "workspace slug",
            seed.ApiKeyRow(
                slug="typo-corp",
                email="user1@example.com",
                name="typo",
                permissions=["member:read"],
            ),
        ),
        (
            "API_KEYS",
            "user email",
            seed.ApiKeyRow(
                slug="acme-corp",
                email=_GHOST_EMAIL,
                name="typo",
                permissions=["member:read"],
            ),
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
    value = bad_row.slug if kind == "workspace slug" else bad_row.email

    with pytest.raises(RuntimeError, match=rf"{label} fixture names unknown {kind} {value!r}"):
        await seed_main()


@pytest.mark.parametrize(
    ("attr", "row", "checked"),
    [
        (
            "MEMBERSHIPS",
            seed.MembershipRow(slug="acme-corp", email=_GHOST_EMAIL, role="editor"),
            True,
        ),
        (
            "INVITATIONS",
            seed.InvitationRow(slug="acme-corp", email=_GHOST_EMAIL, role="viewer"),
            False,
        ),
        (
            "API_KEYS",
            seed.ApiKeyRow(
                slug="acme-corp",
                email=_GHOST_EMAIL,
                name="ghost",
                permissions=["member:read"],
            ),
            True,
        ),
        (
            "_notifications",
            seed.NotificationRow(slug="acme-corp", email=_GHOST_EMAIL, **_NOTIFICATION),
            True,
        ),
    ],
    ids=["memberships", "invitations", "api keys", "notifications"],
)
async def test_email_check_covers_exactly_the_loops_that_read_users(
    monkeypatch, attr, row, checked
):
    """#915: one place states which fixtures must name a registered demo user.

    ``_check_fixtures`` keeps a per-fixture flag that is a copy of which loop
    reads ``users[row.email]``. This asserts the copy in both directions: a
    checked fixture rejects an unregistered address, and the one exempt fixture
    accepts it. A loop that starts reading ``users[row.email]`` while the flag
    stays false fails here with a bare ``KeyError`` instead of the named error.
    """
    _append_row(monkeypatch, attr, row)

    if checked:
        with pytest.raises(RuntimeError, match=rf"unknown user email {_GHOST_EMAIL!r}"):
            await seed_main()
        return

    await seed_main()

    async with SessionFactory() as session:
        invited = (await session.execute(select(Invitation.email))).scalars().all()
    assert _GHOST_EMAIL in invited, "the exempt fixture must seed the invitation"


async def test_invitation_to_an_unregistered_address_is_not_a_failure(monkeypatch):
    """``INVITATIONS`` may name an address the seed never registered.

    The loop invites the address as a string and reads only
    ``users["admin@example.com"]`` for the inviter, so an unregistered invitee is
    the accept-invitation flow, not a typo. An email check that covered this
    fixture would forbid the flow it exists to demo.
    """
    monkeypatch.setattr(
        seed,
        "INVITATIONS",
        [
            *seed.INVITATIONS,
            seed.InvitationRow(slug="acme-corp", email="newcomer@example.com", role="viewer"),
        ],
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
    acme_notifications = sum(1 for row in seed._notifications() if row.slug == "acme-corp")

    assert list(slugs) == ["acme-corp"], "globex rows must be skipped, not created"
    assert len(notifications) == acme_notifications, "the acme-corp rows must still land"
