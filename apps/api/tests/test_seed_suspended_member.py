"""Issue #509: a suspended workspace member must not abort the dev seed.

``seed.main`` asks whether a member row exists with ``has_member_row`` — status
blind, so a suspended row still counts — while ``ApiKeyService.create_api_key``
resolves the actor with ``get_membership``, active rows only, and refuses.
Unhandled, that refusal killed the run on the first key: no keys for the other
workspaces, no invitations, no notifications.
"""

import pytest
from sqlalchemy import func, select

from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.core import Notification
from src.models.workspace import User, Workspace, WorkspaceMember
from src.seed import API_KEYS, DEMO_PASSWORD
from src.seed import main as seed_main
from src.services.api_keys import ApiKeyForbidden
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService

ACME = "acme-corp"


async def _acme_owner(*, status: str = "active", role: str = "owner") -> None:
    """Give the demo admin the acme-corp fixture workspace up front.

    The seed reuses a workspace it finds by slug, so building the row here lets
    one ``seed_main()`` cover the whole run instead of two. ``status`` and
    ``role`` are written out of band, the only way the app can reach them: the
    seed's ``MEMBERSHIPS`` loop never resets either, and the seed re-joins the
    admin only when a row is missing.
    """
    async with SessionFactory() as session:
        admin = await AuthService(session).register(
            email="admin@example.com",
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
        )
        service = WorkspaceService(session)
        workspace = await service.create_workspace(
            name="Acme Corp", slug=ACME, description=None, owner=admin
        )
        member = await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == admin.id,
            )
        )
        row = member.scalar_one()
        row.status = status
        if role != "owner":
            row.role_id = next(
                found.id for found in await service.list_roles(workspace.id) if found.name == role
            )
        await session.commit()


async def _keys_by_user(slug: str) -> dict[str, set[str]]:
    async with SessionFactory() as session:
        workspace_id = await session.scalar(select(Workspace.id).where(Workspace.slug == slug))
        rows = (
            await session.execute(
                select(User.email, ApiKey.name)
                .join(User, User.id == ApiKey.created_by_user_id)
                .where(ApiKey.workspace_id == workspace_id)
            )
        ).all()
    keys: dict[str, set[str]] = {}
    for email, name in rows:
        keys.setdefault(email, set()).add(name)
    return keys


async def test_suspended_owner_skips_its_keys_and_the_seed_finishes():
    await _acme_owner(status="suspended", role="owner")

    await seed_main()  # the regression: used to raise ApiKeyForbidden

    # The suspended admin mints nothing in acme-corp; user1, added as an active
    # editor by the MEMBERSHIPS loop, still does.
    assert await _keys_by_user(ACME) == {
        "user1@example.com": {
            row.name for row in API_KEYS if row.slug == ACME and row.email == "user1@example.com"
        }
    }
    # globex is created by this run, so its keys and its notifications exist
    # only if the run got past the skip above.
    assert await _keys_by_user("globex") == {
        "user1@example.com": {row.name for row in API_KEYS if row.slug == "globex"}
    }
    async with SessionFactory() as session:
        globex_id = await session.scalar(select(Workspace.id).where(Workspace.slug == "globex"))
        seeded = await session.scalar(
            select(func.count())
            .select_from(Notification)
            .where(Notification.workspace_id == globex_id)
        )
        assert seeded > 0


async def test_a_refusal_that_is_not_a_suspended_member_stays_fatal():
    """Suspension is the only refusal the seed swallows.

    A viewer admin can hold a member row that is perfectly active and still
    fail the seed's own permission ceiling on ``API_KEYS``; that is a fixture
    bug, so it must go on aborting the run.
    """
    await _acme_owner(status="active", role="viewer")

    with pytest.raises(ApiKeyForbidden, match="cannot grant permissions"):
        await seed_main()
