"""#586: a fixture row naming a slug or email the seed does not define must fail the seed.

The seed's per-run guards (``if slug not in workspaces: continue``) skip a slug
that is known but absent from this run — single-workspace mode and the
foreign-workspace case both depend on that. They also swallow a slug no fixture
defines at all, which is a typo in code a reviewer reads, and ``users[email]``
turns an undefined email into a bare ``KeyError`` naming neither the fixture nor
the row. Either way the demo ships with rows quietly missing.

``_check_fixtures`` separates the two cases and runs before any DB work, so a
bad row leaves no half-seeded database behind.
"""

import pytest
from sqlalchemy import select

from src import seed
from src.db.session import SessionFactory
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

    with pytest.raises(RuntimeError, match="unknown workspace slug"):
        await seed_main()

    async with SessionFactory() as session:
        rows = (await session.execute(select(Workspace))).scalars().all()
    assert rows == [], "the check must run before the seed writes anything"


async def test_seed_fails_on_unknown_notification_email(monkeypatch):
    _with_notification(monkeypatch, email="ghost@example.com", slug="acme-corp")

    with pytest.raises(RuntimeError, match="unknown user email"):
        await seed_main()


@pytest.mark.parametrize(
    ("fixture", "bad_slug_row", "bad_email_row"),
    [
        (
            "MEMBERSHIPS",
            ("typo-corp", "user1@example.com", "editor"),
            ("acme-corp", "ghost@example.com", "editor"),
        ),
        (
            "INVITATIONS",
            ("typo-corp", "user2@example.com", "viewer"),
            ("acme-corp", "ghost@example.com", "viewer"),
        ),
        (
            "API_KEYS",
            ("typo-corp", "user1@example.com", "typo", ["member:read"]),
            ("acme-corp", "ghost@example.com", "typo", ["member:read"]),
        ),
    ],
)
@pytest.mark.parametrize("field", ["bad_slug_row", "bad_email_row"])
async def test_seed_rejects_undefined_reference_in_every_fixture(
    monkeypatch, fixture, bad_slug_row, bad_email_row, field
):
    bad = bad_slug_row if field == "bad_slug_row" else bad_email_row
    monkeypatch.setattr(seed, fixture, [*getattr(seed, fixture), bad])
    match = "unknown workspace slug" if field == "bad_slug_row" else "unknown user email"

    with pytest.raises(RuntimeError, match=match):
        await seed_main()


async def test_single_workspace_slug_skip_is_not_a_failure(monkeypatch):
    """The skip guards stay for a slug that is known but not part of this run.

    Single-workspace mode puts only ``acme-corp`` in the run, so every
    ``globex`` row takes the skip path. Raising there would break every
    single-workspace seed, so the check must reject a slug the fixtures never
    define and nothing else.
    """
    monkeypatch.setattr(settings, "single_workspace", True)

    await seed_main()
