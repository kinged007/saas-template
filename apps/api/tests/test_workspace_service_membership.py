"""`has_member_row` answers "does a member row exist"; `get_membership` is active-only."""

import pytest
from sqlalchemy import select

from src.db.session import SessionFactory
from src.models.workspace import WorkspaceMember
from src.seed import DEMO_PASSWORD
from src.services.auth import AuthService
from src.services.workspaces import WorkspaceService


async def _workspace_with_suspended_owner_row(email: str) -> str:
    """Register `email`, give them a workspace, suspend their member row.

    Returns the workspace id. The owner row is the only member row, so
    suspending it exercises "row exists" and "not an active membership"
    at once.
    """
    async with SessionFactory() as session:
        service = WorkspaceService(session)
        admin = await AuthService(session).register(
            email=email,
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
        )
        workspace = await service.create_workspace(
            name="Acme", slug="acme-corp", description=None, owner=admin
        )
        member = await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace.id)
        )
        member.scalar_one().status = "suspended"
        await session.commit()
        return workspace.id


async def test_has_member_row_sees_a_suspended_row():
    """A suspended row is still a row: True where get_membership reads None."""
    workspace_id = await _workspace_with_suspended_owner_row("row-admin@example.com")

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        admin = await AuthService(session).get_by_email("row-admin@example.com")

        assert await service.has_member_row(workspace_id, admin.id) is True
        assert await service.get_membership(workspace_id, admin.id) is None


async def test_has_member_row_false_without_a_row():
    async with SessionFactory() as session:
        service = WorkspaceService(session)
        admin = await AuthService(session).register(
            email="alone-admin@example.com",
            password=DEMO_PASSWORD,
            first_name="Admin",
            last_name="User",
        )
        outsider = await AuthService(session).register(
            email="outsider@example.com",
            password=DEMO_PASSWORD,
            first_name="Out",
            last_name="Sider",
        )
        workspace = await service.create_workspace(
            name="Acme", slug="acme-corp", description=None, owner=admin
        )

        assert await service.has_member_row(workspace.id, outsider.id) is False


async def test_has_member_row_tolerates_duplicate_rows():
    """Two rows for one (workspace_id, user_id) must not raise: existence check."""
    workspace_id = await _workspace_with_suspended_owner_row("dup-admin@example.com")

    async with SessionFactory() as session:
        service = WorkspaceService(session)
        admin = await AuthService(session).get_by_email("dup-admin@example.com")
        first = await session.execute(
            select(WorkspaceMember).where(WorkspaceMember.workspace_id == workspace_id)
        )
        original = first.scalar_one()
        duplicate = WorkspaceMember(
            workspace_id=workspace_id,
            user_id=admin.id,
            role_id=original.role_id,
            status="active",
        )
        session.add(duplicate)
        await session.commit()

        assert await service.has_member_row(workspace_id, admin.id) is True


async def test_get_membership_rejects_the_active_only_flag():
    """The opt-out is gone: passing active_only fails loudly, not silently."""
    async with SessionFactory() as session:
        service = WorkspaceService(session)

        with pytest.raises(TypeError):
            await service.get_membership("ws-id", "user-id", active_only=False)
