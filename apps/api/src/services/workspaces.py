from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.core.permissions import permissions_for_role
from src.events.bus import EventBus
from src.events.subjects import Subjects
from src.models.core import Invitation
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.services.auth import AuthService


class WorkspaceError(Exception):
    pass


class WorkspaceForbidden(WorkspaceError):
    pass


class WorkspaceConflict(WorkspaceError):
    pass


class WorkspaceService:
    DEFAULT_ROLES = ["owner", "admin", "editor", "viewer"]

    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    # ------------------------------------------------------------- workspaces

    async def create_workspace(
        self, *, name: str, slug: str | None, description: str | None, owner: User
    ) -> Workspace:
        slug = slug or _slugify(name)
        exists = await self._session.execute(select(Workspace).where(Workspace.slug == slug))
        if exists.scalar_one_or_none():
            raise WorkspaceError("a workspace with that slug already exists")
        workspace = Workspace(
            name=name, slug=slug, description=description, created_by_user_id=owner.id
        )
        self._session.add(workspace)
        await self._session.flush()
        for role_name in self.DEFAULT_ROLES:
            self._session.add(
                Role(
                    workspace_id=workspace.id,
                    name=role_name,
                    permissions=permissions_for_role(role_name),
                    system=True,
                    description=f"Default {role_name} role",
                )
            )
        owner_role = await self._role_by_name(workspace.id, "owner")
        self._session.add(
            WorkspaceMember(
                workspace_id=workspace.id,
                user_id=owner.id,
                role_id=owner_role.id,
                status="active",
            )
        )
        await self._session.commit()
        return workspace

    async def list_workspaces(self, user_id: str) -> list[tuple[Workspace, Role, WorkspaceMember]]:
        stmt = (
            select(Workspace, Role, WorkspaceMember)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .join(Role, Role.id == WorkspaceMember.role_id)
            .where(WorkspaceMember.user_id == user_id, WorkspaceMember.status == "active")
            .order_by(Workspace.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.all())

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def get_membership(
        self, workspace_id: str, user_id: str
    ) -> tuple[WorkspaceMember, Role] | None:
        stmt = (
            select(WorkspaceMember, Role)
            .join(Role, Role.id == WorkspaceMember.role_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        result = await self._session.execute(stmt)
        return result.first()

    # ---------------------------------------------------------------- members

    async def list_members(self, workspace_id: str) -> list[tuple[WorkspaceMember, User, Role]]:
        stmt = (
            select(WorkspaceMember, User, Role)
            .join(User, User.id == WorkspaceMember.user_id)
            .join(Role, Role.id == WorkspaceMember.role_id)
            .where(WorkspaceMember.workspace_id == workspace_id)
            .order_by(WorkspaceMember.created_at.asc())
        )
        result = await self._session.execute(stmt)
        return list(result.all())

    async def set_member_role(
        self, workspace_id: str, member_id: str, role_id: str, *, actor: User
    ) -> WorkspaceMember:
        membership = await self.get_membership(workspace_id, actor.id)
        if membership is None:
            raise WorkspaceForbidden("you are not a member of this workspace")
        _, actor_role = membership
        if actor_role.name not in ("owner", "admin"):
            raise WorkspaceForbidden("only the workspace owner or an admin can change roles")
        member = await self._session.get(WorkspaceMember, member_id)
        if member is None or member.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        current_role = await self._session.get(Role, member.role_id)
        if current_role is not None and current_role.name == "owner":
            raise WorkspaceConflict("cannot change the workspace owner's role")
        role = await self._session.get(Role, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise WorkspaceError("role not found in workspace")
        if role.name == "owner":
            raise WorkspaceConflict("cannot assign the owner role")
        member.role_id = role.id
        await self._session.commit()
        return member

    async def remove_member(self, workspace_id: str, member_id: str, *, actor: User) -> None:
        member = await self._session.get(WorkspaceMember, member_id)
        if member is None or member.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        if member.user_id == actor.id:
            raise WorkspaceError("cannot remove yourself")
        role = await self._session.get(Role, member.role_id)
        if role and role.name == "owner":
            raise WorkspaceError("cannot remove the workspace owner")
        await self._session.delete(member)
        await self._session.commit()

    # ------------------------------------------------------------- invitations

    async def create_invitation(
        self,
        *,
        workspace: Workspace,
        email: str,
        role: Role,
        invited_by: User,
        expires_in_hours: int = 72,
    ) -> Invitation:
        email = email.lower()
        if role.name == "owner":
            raise WorkspaceConflict("cannot invite a user to the owner role")
        duplicate = await self._session.execute(
            select(Invitation).where(
                Invitation.workspace_id == workspace.id,
                Invitation.email == email,
                Invitation.status == "pending",
            )
        )
        if duplicate.scalar_one_or_none():
            raise WorkspaceError("a pending invitation already exists for this email")
        invite = Invitation(
            workspace_id=workspace.id,
            email=email,
            role_id=role.id,
            invited_by_user_id=invited_by.id,
            token=secrets.token_urlsafe(32),
            status="pending",
            expires_at=now_utc() + timedelta(hours=expires_in_hours),
        )
        self._session.add(invite)
        await self._session.commit()

        # Notify an existing user with that email via the event bus.
        existing = await AuthService(self._session).get_by_email(email)
        if existing and existing.id != invited_by.id and self._bus is not None:
            await self._bus.publish(
                Subjects.WORKSPACE_MEMBER_INVITED,
                {
                    "user_id": existing.id,
                    "workspace_id": workspace.id,
                    "workspace_name": workspace.name,
                    "invitation_id": invite.id,
                    "invited_by": invited_by.display_name,
                    "title": f"You were invited to {workspace.name}",
                    "body": (
                        f"{invited_by.display_name} invited you to the {workspace.name} workspace."
                    ),
                },
            )
        return invite

    async def list_invitations(self, workspace_id: str) -> list[Invitation]:
        stmt = (
            select(Invitation)
            .where(Invitation.workspace_id == workspace_id)
            .order_by(Invitation.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_received_invitations(
        self, user: User
    ) -> list[tuple[Invitation, Workspace, User]]:
        """Invitations issued to this user's email, across all workspaces."""
        stmt = (
            select(Invitation, Workspace, User)
            .join(Workspace, Workspace.id == Invitation.workspace_id)
            .join(User, User.id == Invitation.invited_by_user_id)
            .where(Invitation.email == user.email.lower())
            .order_by(Invitation.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.all())

    async def decline_invitation(self, invitation_id: str, user: User) -> Invitation:
        invite = await self._session.get(Invitation, invitation_id)
        if invite is None or invite.email != user.email.lower():
            raise WorkspaceError("invitation not found")
        if invite.status != "pending":
            raise WorkspaceConflict("invitation is no longer pending")
        if ensure_utc(invite.expires_at) < now_utc():
            invite.status = "revoked"
            await self._session.commit()
            raise WorkspaceConflict("invitation has expired")
        invite.status = "declined"
        await self._session.commit()
        return invite

    async def revoke_invitation(self, workspace_id: str, invitation_id: str) -> Invitation:
        invite = await self._session.get(Invitation, invitation_id)
        if invite is None or invite.workspace_id != workspace_id:
            raise WorkspaceError("invitation not found")
        if invite.status != "pending":
            raise WorkspaceError("invitation is no longer pending")
        invite.status = "revoked"
        await self._session.commit()
        return invite

    async def accept_invitation(self, token: str, user: User) -> Workspace:
        stmt = select(Invitation).where(Invitation.token == token)
        result = await self._session.execute(stmt)
        invite = result.scalar_one_or_none()
        if invite is None or invite.status != "pending":
            raise WorkspaceError("invitation not found or no longer valid")
        if ensure_utc(invite.expires_at) < now_utc():
            invite.status = "revoked"
            await self._session.commit()
            raise WorkspaceError("invitation has expired")
        if invite.email != user.email.lower():
            raise WorkspaceError("this invitation was issued for a different email")

        existing = await self._session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == invite.workspace_id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none() is None:
            self._session.add(
                WorkspaceMember(
                    workspace_id=invite.workspace_id,
                    user_id=user.id,
                    role_id=invite.role_id,
                    status="active",
                )
            )
        invite.status = "accepted"
        invite.accepted_at = now_utc()
        await self._session.commit()
        workspace = await self._session.get(Workspace, invite.workspace_id)
        if self._bus is not None:
            await self._bus.publish(
                Subjects.WORKSPACE_MEMBER_JOINED,
                {
                    "workspace_id": workspace.id,
                    "user_id": user.id,
                    "workspace_name": workspace.name,
                },
            )
        return workspace

    # ------------------------------------------------------------------ roles

    async def list_roles(self, workspace_id: str) -> list[Role]:
        stmt = select(Role).where(Role.workspace_id == workspace_id).order_by(Role.created_at.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _role_by_name(self, workspace_id: str, name: str) -> Role:
        stmt = select(Role).where(Role.workspace_id == workspace_id, Role.name == name)
        result = await self._session.execute(stmt)
        role = result.scalar_one_or_none()
        if role is None:
            raise WorkspaceError(f"role {name} not found")
        return role

    async def create_custom_role(
        self, workspace_id: str, *, name: str, description: str | None, permissions: list[str]
    ) -> Role:
        role = Role(
            workspace_id=workspace_id,
            name=name,
            description=description,
            permissions=permissions,
            system=False,
        )
        self._session.add(role)
        await self._session.commit()
        return role


def _slugify(name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    return slug or f"ws-{uuid.uuid4().hex[:8]}"
