from datetime import timedelta

import pytest
from sqlalchemy import select

from src.core.dates import now_utc
from src.db.session import SessionFactory
from src.models.api_key import ApiKey
from src.models.core import Invitation, Notification
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.seed import DEMO_PASSWORD
from src.seed import main as seed_main
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService
from src.settings import settings


@pytest.fixture
def single_workspace_on(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", True)


async def _workspaces() -> dict[str, str]:
    async with SessionFactory() as session:
        stmt = select(Workspace).order_by(Workspace.created_at, Workspace.id)
        result = await session.execute(stmt)
        return {workspace.id: workspace.slug for workspace in result.scalars()}


async def test_seed_creates_only_first_workspace_in_single_mode(single_workspace_on):
    await seed_main()

    assert list((await _workspaces()).values()) == ["acme-corp"]


async def test_seed_creates_demo_data_in_clean_single_mode(single_workspace_on):
    """On a clean database, single mode seeds only the acme-corp workspace.

    The workspace gets the full demo fixture set, and the assertions pin the
    exact rows so an extra fixture entry fails here instead of passing
    silently: three API keys (`ci-deploy`, `automation`, `editor-script`),
    one invitation (`user2@example.com`) and three notifications
    (admin/user1/user2). No globex fixture rows, no drift-blind gaps.
    """
    await seed_main()

    async with SessionFactory() as session:
        api_keys = (await session.execute(select(ApiKey.name))).scalars().all()
        invites = (await session.execute(select(Invitation.email))).scalars().all()
        notifications = (
            await session.execute(
                select(User.email, Notification.title).join(User, User.id == Notification.user_id)
            )
        ).all()

        assert sorted(api_keys) == ["automation", "ci-deploy", "editor-script"], (
            f"api keys: {api_keys}"
        )
        assert invites == ["user2@example.com"], f"invitations: {invites}"
        # A set, not a list: select order is not pinned, and sorted() cannot
        # order (email, title) pairs against each other's tuple shape.
        assert set(notifications) == {
            ("admin@example.com", "New invitation sent"),
            ("user1@example.com", "You were invited to Acme Corp"),
            ("user2@example.com", "You were invited to Acme Corp"),
        }, f"notifications: {notifications}"


async def test_seed_reuses_oldest_workspace_in_single_mode(single_workspace_on, monkeypatch):
    # Create both fixtures with the flag off: in single mode the second
    # create_workspace() is rejected by design.
    monkeypatch.setattr(settings, "single_workspace", False)
    async with SessionFactory() as session:
        owner = await AuthService(session).register(
            email="admin@example.com",
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
        )
        service = WorkspaceService(session)
        first = await service.create_workspace(
            name="First", slug="first", description=None, owner=owner
        )
        second = await service.create_workspace(
            name="Second", slug="second", description=None, owner=owner
        )
        first.created_at = now_utc() - timedelta(days=1)
        second.created_at = now_utc()
        await session.commit()
        first_id, second_id = first.id, second.id

    monkeypatch.setattr(settings, "single_workspace", True)
    await seed_main()

    assert await _workspaces() == {first_id: "first", second_id: "second"}
    async with SessionFactory() as session:
        first_key = await session.scalar(select(ApiKey.id).where(ApiKey.workspace_id == first_id))
        second_key = await session.scalar(select(ApiKey.id).where(ApiKey.workspace_id == second_id))
        assert first_key is not None
        assert second_key is None


async def test_seed_skips_demo_data_for_foreign_single_workspace(single_workspace_on):
    """A workspace created by a non-demo user stays free of demo fixtures.

    A developer who registers before the first seed owns the canonical
    workspace, and the demo admin only gains a membership by logging in.
    """
    async with SessionFactory() as session:
        real = await AuthService(session).register(
            email="real@dev.example",
            password=DEMO_PASSWORD,
            first_name="Real",
            last_name="Dev",
        )
        await WorkspaceService(session).join_single_workspace(real)

    await seed_main()

    assert list((await _workspaces()).values()) == ["workspace"]
    async with SessionFactory() as session:
        for model in (ApiKey, Invitation, Notification):
            result = await session.execute(select(model.id))
            assert result.scalars().all() == [], f"unexpected {model.__name__} rows"


async def test_seed_registers_fixture_when_canonical_workspace_has_no_owner_member(
    single_workspace_on, monkeypatch
):
    """A canonical workspace with nobody in its owner role still gets the fixture.

    No membership holds the owner role, so the guard's `owner is None` arm is
    what admits the workspace. The app blocks every route to this state —
    `remove_member`, `leave_workspace` and `set_member_role` all refuse the
    owner, and roles cannot be deleted — so the branch is defensive. The test
    reaches it the only way the seed could see it in production: an
    out-of-band write of `role_id`. The demo admin is not a member here, so the
    fixture attaches on registration. Only rows keyed to the admitted
    acme-corp fixture are created — the admin-keyed ones are gated on
    membership — and the assertions pin the exact set: one API key
    (`editor-script`), one invitation (`user2@example.com`) and three
    notifications (admin/user1/user2). A fifth API_KEYS entry or an extra
    fixture row for the canonical workspace therefore fails here, instead of
    only invalidating this docstring's enumeration.
    """
    monkeypatch.setattr(settings, "single_workspace", False)
    async with SessionFactory() as session:
        other = await AuthService(session).register(
            email="other@dev.example",
            password=DEMO_PASSWORD,
            first_name="Other",
            last_name="Dev",
        )
        service = WorkspaceService(session)
        workspace = await service.create_workspace(
            name="First", slug="first", description=None, owner=other
        )
        viewer = next(
            role for role in await service.list_roles(workspace.id) if role.name == "viewer"
        )
        membership = await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == other.id,
            )
        )
        membership.scalar_one().role_id = viewer.id
        await session.commit()
        workspace_id = workspace.id

    monkeypatch.setattr(settings, "single_workspace", True)
    await seed_main()

    assert await _workspaces() == {workspace_id: "first"}
    async with SessionFactory() as session:
        api_keys = (
            (await session.execute(select(ApiKey.name).where(ApiKey.workspace_id == workspace_id)))
            .scalars()
            .all()
        )
        invites = (
            (
                await session.execute(
                    select(Invitation.email).where(Invitation.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        notifications = (
            await session.execute(
                select(User.email, Notification.title)
                .join(User, User.id == Notification.user_id)
                .where(Notification.workspace_id == workspace_id)
            )
        ).all()

        assert api_keys == ["editor-script"], f"api keys in {workspace_id}: {api_keys}"
        assert invites == ["user2@example.com"], f"invitations in {workspace_id}: {invites}"
        # A set, not a list: the fixture rows carry offsets that tie at the
        # same created_at, so select order is not pinned.
        assert set(notifications) == {
            ("admin@example.com", "New invitation sent"),
            ("user1@example.com", "You were invited to Acme Corp"),
            ("user2@example.com", "You were invited to Acme Corp"),
        }, f"notifications in {workspace_id}: {notifications}"


async def test_seed_fails_with_a_clear_error_when_owner_role_is_missing(single_workspace_on):
    """No owner role at all is a hard failure, not a silent skip of the workspace."""
    async with SessionFactory() as session:
        real = await AuthService(session).register(
            email="real@dev.example",
            password=DEMO_PASSWORD,
            first_name="Real",
            last_name="Dev",
        )
        workspace = await WorkspaceService(session).join_single_workspace(real)
        result = await session.execute(
            select(Role).where(Role.workspace_id == workspace.id, Role.name == "owner")
        )
        await session.delete(result.scalar_one())
        await session.commit()

    with pytest.raises(RuntimeError, match="role owner not found"):
        await seed_main()


async def test_seed_keeps_both_workspaces_when_single_mode_is_off(monkeypatch):
    monkeypatch.setattr(settings, "single_workspace", False)

    await seed_main()

    assert set((await _workspaces()).values()) == {"acme-corp", "globex"}


async def test_seed_api_key_guard_looks_for_the_row_not_the_status(single_workspace_on):
    """The seed guard asks whether a member row exists at all, not its status.

    A suspended owner row is still a row, so the guard — `has_member_row`,
    which ignores status — admits the workspace, and ApiKeyService, which
    resolves the actor with `get_membership`, is what refuses the mint. An
    active-only membership check in the guard would skip the key silently
    instead.
    """
    from src.services.api_keys import ApiKeyForbidden

    async with SessionFactory() as session:
        admin = await AuthService(session).register(
            email="admin@example.com",
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
        )
        workspace = await WorkspaceService(session).create_workspace(
            name="Acme", slug="acme-corp", description=None, owner=admin
        )
        member = await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)
        )
        member.scalar_one().status = "suspended"
        await session.commit()

    with pytest.raises(ApiKeyForbidden):
        await seed_main()
