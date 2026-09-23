from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import ensure_utc, now_utc
from src.core.permissions import (
    ALL_PERMISSIONS,
    KEY_ONLY_PERMISSIONS,
    permissions_for_role,
)
from src.events.bus import EventBus
from src.events.publisher import publish_audit, publish_event
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

    # Auto-join role for single-workspace mode (SINGLE_WORKSPACE). Viewer:
    # edit access requires explicit designation.
    SINGLE_WORKSPACE_ROLE = "viewer"

    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    # ------------------------------------------------------- single workspace

    @staticmethod
    def single_workspace_enabled() -> bool:
        from src.settings import settings

        return settings.single_workspace

    async def get_single_workspace(self) -> Workspace | None:
        """Oldest workspace wins (covers "workspace[0]" when rows pre-exist)."""
        result = await self._session.execute(
            select(Workspace).order_by(Workspace.created_at.asc()).limit(1)
        )
        return result.scalar_one_or_none()

    async def join_single_workspace(self, user: User) -> Workspace:
        """Ensure the shared workspace exists, then add the user idempotently.

        First arrival creates it (owned by them, normally the superadmin);
        everyone else joins as viewer. Existing members keep their role."""
        workspace = await self.get_single_workspace()
        if workspace is None:
            try:
                return await self.create_workspace(
                    name="Workspace",
                    slug=None,
                    description=None,
                    owner=user,
                    allow_single_workspace_bootstrap=True,
                )
            except (WorkspaceError, IntegrityError):
                # Lost the first-login race: the winner's row is now oldest.
                # IntegrityError covers the concurrent case where two
                # bootstraps both pass the slug check and the loser hits the
                # UNIQUE constraint on workspace.slug.
                await self._session.rollback()
                workspace = await self.get_single_workspace()
                if workspace is None:
                    raise
        existing = await self._session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace.id,
                WorkspaceMember.user_id == user.id,
            )
        )
        if existing.scalar_one_or_none() is None:
            role = await self._single_workspace_role(workspace.id)
            self._session.add(
                WorkspaceMember(
                    workspace_id=workspace.id,
                    user_id=user.id,
                    role_id=role.id,
                    status="active",
                )
            )
            await self._session.commit()
        return workspace

    # ------------------------------------------------------------- workspaces

    async def create_workspace(
        self,
        *,
        name: str,
        slug: str | None,
        description: str | None,
        owner: User,
        ip_address: str | None = None,
        allow_single_workspace_bootstrap: bool = False,
    ) -> Workspace:
        if self.single_workspace_enabled() and not allow_single_workspace_bootstrap:
            existing = await self.get_single_workspace()
            if existing is not None:
                raise WorkspaceForbidden("single-workspace mode: only one workspace is allowed")
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

        await publish_event(
            self._bus,
            Subjects.WORKSPACE_CREATED,
            {
                "workspace_id": workspace.id,
                "name": workspace.name,
                "slug": workspace.slug,
                "created_by_user_id": owner.id,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace.id,
            resource_type="workspace",
            resource_id=workspace.id,
            action="workspace.created",
            actor_user_id=owner.id,
            details={"name": workspace.name, "slug": workspace.slug},
            ip_address=ip_address,
        )
        return workspace

    async def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> Workspace:
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceError("workspace not found")
        changes: dict = {}
        if name is not None and name != workspace.name:
            changes["name"] = {"from": workspace.name, "to": name}
            workspace.name = name
        if description is not None and description != workspace.description:
            changes["description"] = {"from": workspace.description, "to": description}
            workspace.description = description
        await self._session.commit()
        if changes:
            await publish_audit(
                self._bus,
                workspace_id=workspace_id,
                resource_type="workspace",
                resource_id=workspace_id,
                action="workspace.updated",
                actor_user_id=actor.id if actor else None,
                details=changes,
                ip_address=ip_address,
            )
        return workspace

    async def delete_workspace(
        self,
        workspace_id: str,
        *,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> None:
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceError("workspace not found")
        if self.single_workspace_enabled():
            raise WorkspaceForbidden("single-workspace mode: workspaces cannot be deleted")
        name = workspace.name

        # --- Cascade delete workspace-scoped data (see src/db/cascade.py).
        # Users themselves are global and are NOT deleted — only memberships and
        # workspace-scoped resources. AuditLogEntry rows are the one exemption:
        # append-only compliance trail, nothing ever deletes them.
        # Conversation/JobDefinition are in the registry for coverage, but
        # deleted last here (parents after children).
        from src.db.cascade import (
            CONVERSATION_CHILDREN,
            JOB_RUN_CHILDREN,
            WORKSPACE_CASCADE,
        )
        from src.models.conversation import Conversation
        from src.models.jobs import JobDefinition, JobRun

        for model in WORKSPACE_CASCADE:
            if model in (Conversation, JobRun, JobDefinition):
                continue  # parents: deleted after their children below
            await self._session.execute(delete(model).where(model.workspace_id == workspace_id))
        # Children linked indirectly (no workspace_id of their own): collect
        # parent ids first, then delete grandchildren → children → parents so
        # plain StringUUID columns (no DB-level cascades) leave no orphans.
        conv_ids = [
            row[0]
            for row in (
                await self._session.execute(
                    select(Conversation.id).where(Conversation.workspace_id == workspace_id)
                )
            ).all()
        ]
        if conv_ids:
            for child in CONVERSATION_CHILDREN:
                for chunk in _chunks(conv_ids):
                    await self._session.execute(
                        delete(child).where(child.conversation_id.in_(chunk))
                    )
        definition_ids = [
            row[0]
            for row in (
                await self._session.execute(
                    select(JobDefinition.id).where(JobDefinition.workspace_id == workspace_id)
                )
            ).all()
        ]
        run_ids = [
            row[0]
            for row in (
                await self._session.execute(
                    select(JobRun.id).where(JobRun.workspace_id == workspace_id)
                )
            ).all()
        ]
        if definition_ids:
            run_ids += [
                row[0]
                for row in (
                    await self._session.execute(
                        select(JobRun.id).where(JobRun.definition_id.in_(definition_ids))
                    )
                ).all()
            ]
            for chunk in _chunks(definition_ids):
                await self._session.execute(delete(JobRun).where(JobRun.definition_id.in_(chunk)))
        if run_ids:
            run_ids = list(dict.fromkeys(run_ids))
            for child in JOB_RUN_CHILDREN:
                for chunk in _chunks(run_ids):
                    await self._session.execute(delete(child).where(child.run_id.in_(chunk)))
        await self._session.execute(delete(JobRun).where(JobRun.workspace_id == workspace_id))
        await self._session.execute(
            delete(JobDefinition).where(JobDefinition.workspace_id == workspace_id)
        )
        await self._session.execute(
            delete(Conversation).where(Conversation.workspace_id == workspace_id)
        )

        # Finally delete the workspace row itself
        await self._session.delete(workspace)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="workspace",
            resource_id=workspace_id,
            action="workspace.deleted",
            actor_user_id=actor.id if actor else None,
            details={"name": name},
            ip_address=ip_address,
        )

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
        self,
        workspace_id: str,
        member_id: str,
        role_id: str,
        *,
        actor: User,
        ip_address: str | None = None,
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
        from_role = current_role.name if current_role is not None else None
        member.role_id = role.id
        await self._session.commit()

        workspace = await self._session.get(Workspace, workspace_id)
        await publish_event(
            self._bus,
            Subjects.WORKSPACE_MEMBER_ROLE_CHANGED,
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace.name if workspace else "workspace",
                "user_id": member.user_id,
                "from_role": from_role,
                "to_role": role.name,
                "changed_by_user_id": actor.id,
                "changed_by_name": actor.display_name,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="member",
            resource_id=member.id,
            action="member.role_changed",
            actor_user_id=actor.id,
            details={
                "user_id": member.user_id,
                "from_role": from_role,
                "to_role": role.name,
                "changed_by_name": actor.display_name,
            },
            ip_address=ip_address,
        )
        return member

    async def remove_member(
        self,
        workspace_id: str,
        member_id: str,
        *,
        actor: User,
        ip_address: str | None = None,
    ) -> None:
        member = await self._session.get(WorkspaceMember, member_id)
        if member is None or member.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        if member.user_id == actor.id:
            raise WorkspaceError("cannot remove yourself")
        role = await self._session.get(Role, member.role_id)
        if role and role.name == "owner":
            raise WorkspaceError("cannot remove the workspace owner")
        user_id = member.user_id
        workspace = await self._session.get(Workspace, workspace_id)
        workspace_name = workspace.name if workspace else "workspace"
        await self._session.delete(member)
        await self._session.commit()

        await publish_event(
            self._bus,
            Subjects.WORKSPACE_MEMBER_REMOVED,
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace_name,
                "user_id": user_id,
                "removed_by_user_id": actor.id,
                "removed_by_name": actor.display_name,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="member",
            resource_id=member_id,
            action="member.removed",
            actor_user_id=actor.id,
            details={"user_id": user_id, "workspace_name": workspace_name},
            ip_address=ip_address,
        )

    # ------------------------------------------------------------- invitations

    async def create_invitation(
        self,
        *,
        workspace: Workspace,
        email: str,
        role: Role,
        invited_by: User,
        expires_in_hours: int = 72,
        ip_address: str | None = None,
    ) -> Invitation:
        email = email.lower()
        if (workspace.flags or {}).get("invites_enabled") is False:
            raise WorkspaceError("invitations are disabled for this workspace")
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

        existing = await AuthService(self._session).get_by_email(email)
        is_registered = existing is not None

        # Fired for every invitation. The workflow currently only handles
        # unregistered recipients; email delivery is not implemented yet.
        await publish_event(
            self._bus,
            Subjects.WORKSPACE_INVITATION_CREATED,
            {
                "invitation_id": invite.id,
                "workspace_id": workspace.id,
                "workspace_name": workspace.name,
                "email": email,
                "role": role.name,
                "invited_by_user_id": invited_by.id,
                "invited_by_name": invited_by.display_name,
                "is_registered": is_registered,
                # TODO(events): include an accept URL when email delivery is
                # implemented, e.g.
                # "accept_url": f"{settings.frontend_url}/invitations/accept?token={invite.token}",
            },
        )
        # Notify an existing user with that email via the event bus.
        if is_registered and existing.id != invited_by.id and self._bus is not None:
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
        await publish_audit(
            self._bus,
            workspace_id=workspace.id,
            resource_type="invitation",
            resource_id=invite.id,
            action="invitation.created",
            actor_user_id=invited_by.id,
            details={
                "email": email,
                "role": role.name,
                "workspace_name": workspace.name,
                "expires_in_hours": expires_in_hours,
            },
            ip_address=ip_address,
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

    async def decline_invitation(
        self, invitation_id: str, user: User, *, ip_address: str | None = None
    ) -> Invitation:
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
        await publish_audit(
            self._bus,
            workspace_id=invite.workspace_id,
            resource_type="invitation",
            resource_id=invite.id,
            action="invitation.declined",
            actor_user_id=user.id,
            details={"email": invite.email},
            ip_address=ip_address,
        )
        return invite

    async def revoke_invitation(
        self,
        workspace_id: str,
        invitation_id: str,
        *,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> Invitation:
        invite = await self._session.get(Invitation, invitation_id)
        if invite is None or invite.workspace_id != workspace_id:
            raise WorkspaceError("invitation not found")
        if invite.status != "pending":
            raise WorkspaceError("invitation is no longer pending")
        invite.status = "revoked"
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="invitation",
            resource_id=invite.id,
            action="invitation.revoked",
            actor_user_id=actor.id if actor else None,
            details={"email": invite.email},
            ip_address=ip_address,
        )
        return invite

    async def accept_invitation(
        self, token: str, user: User, *, ip_address: str | None = None
    ) -> Workspace:
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
                    "workspace_name": workspace.name,
                    "user_id": user.id,
                    "user_name": user.display_name,
                    "invited_by_user_id": invite.invited_by_user_id,
                },
            )
        await publish_audit(
            self._bus,
            workspace_id=invite.workspace_id,
            resource_type="invitation",
            resource_id=invite.id,
            action="invitation.accepted",
            actor_user_id=user.id,
            details={"workspace_name": workspace.name, "email": user.email},
            ip_address=ip_address,
        )
        return workspace

    # ------------------------------------------------------------------ roles

    async def sync_system_role_permissions(self) -> int:
        """Converge every workspace's system roles on the code defaults.

        Only rows with `system=True` are touched — custom roles are never
        modified. Idempotent; returns the number of roles whose permission
        list changed. Used when a default role's permission set evolves
        (e.g. granting apikey management to viewers) so existing workspaces
        pick up the change on re-seed instead of only new ones.
        """
        result = await self._session.execute(select(Role).where(Role.system.is_(True)))
        changed = 0
        for role in result.scalars().all():
            try:
                defaults = permissions_for_role(role.name)
            except ValueError:
                continue  # system flag on a renamed/custom role — leave it alone
            if sorted(role.permissions) != sorted(defaults):
                role.permissions = defaults
                changed += 1
        if changed:
            await self._session.commit()
        return changed

    async def list_roles(self, workspace_id: str) -> list[Role]:
        stmt = select(Role).where(Role.workspace_id == workspace_id).order_by(Role.created_at.asc())
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def _single_workspace_role(self, workspace_id: str) -> Role:
        """Auto-join role: viewer, else the lowest non-owner system role.

        Falls back when the viewer role was renamed/removed so a missing
        role does not brick every later login in single-workspace mode."""
        stmt = select(Role).where(Role.workspace_id == workspace_id)
        result = await self._session.execute(stmt)
        roles = list(result.scalars().all())
        for role in roles:
            if role.name == self.SINGLE_WORKSPACE_ROLE:
                return role
        for fallback in ("editor", "admin"):
            for role in roles:
                if role.name == fallback:
                    return role
        non_owner = [r for r in roles if r.name != "owner"]
        if non_owner:
            return non_owner[0]
        raise WorkspaceError(f"role {self.SINGLE_WORKSPACE_ROLE} not found")

    async def _role_by_name(self, workspace_id: str, name: str) -> Role:
        stmt = select(Role).where(Role.workspace_id == workspace_id, Role.name == name)
        result = await self._session.execute(stmt)
        role = result.scalar_one_or_none()
        if role is None:
            raise WorkspaceError(f"role {name} not found")
        return role

    def _check_permissions_assignable(
        self, permissions: list[str], assignable: set[str], *, owner: bool = False
    ) -> None:
        """Unknown strings and `"*"` fail fast; unheld permissions are Forbidden."""
        unknown = sorted(
            set(permissions) - set(ALL_PERMISSIONS) - {"*"} - set(KEY_ONLY_PERMISSIONS)
        )
        if unknown:
            raise WorkspaceError(f"unknown permissions: {', '.join(unknown)}")
        if "*" in permissions:
            # Reserved for owner — minting it would clone owner minus the name.
            raise WorkspaceError('"*" is reserved for the owner role')
        if not owner:
            denied = sorted(set(permissions) - assignable)
            if denied:
                raise WorkspaceForbidden(
                    f"cannot grant permissions you do not have: {', '.join(denied)}"
                )

    async def _check_name_free(
        self, workspace_id: str, name: str, *, exclude_id: str | None = None
    ) -> None:
        stmt = select(Role).where(Role.workspace_id == workspace_id, Role.name == name)
        if exclude_id is not None:
            stmt = stmt.where(Role.id != exclude_id)
        if (await self._session.execute(stmt)).scalar_one_or_none() is not None:
            raise WorkspaceConflict(f"a role named '{name}' already exists")

    async def create_custom_role(
        self,
        workspace_id: str,
        *,
        name: str,
        description: str | None,
        permissions: list[str],
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> Role:
        assignable: set[str] = set()
        is_owner = False
        if actor is not None:
            membership = await self.get_membership(workspace_id, actor.id)
            if membership is not None:
                _, actor_role = membership
                is_owner = "*" in actor_role.permissions
                assignable = set(actor_role.permissions)
        self._check_permissions_assignable(permissions, assignable, owner=is_owner)
        await self._check_name_free(workspace_id, name)
        role = Role(
            workspace_id=workspace_id,
            name=name,
            description=description,
            permissions=permissions,
            system=False,
        )
        self._session.add(role)
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="role",
            resource_id=role.id,
            action="role.created",
            actor_user_id=actor.id if actor else None,
            details={"name": name, "permissions": permissions},
            ip_address=ip_address,
        )
        return role

    async def update_role(
        self,
        workspace_id: str,
        role_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        permissions: list[str] | None = None,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> Role:
        role = await self._session.get(Role, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise WorkspaceError("role not found")
        if role.name == "owner":
            raise WorkspaceForbidden("the owner role cannot be edited")
        if name is not None and name != role.name:
            await self._check_name_free(workspace_id, name, exclude_id=role.id)
            role.name = name
        if description is not None:
            role.description = description
        if permissions is not None:
            assignable: set[str] = set()
            is_owner = False
            if actor is not None:
                membership = await self.get_membership(workspace_id, actor.id)
                if membership is not None:
                    _, actor_role = membership
                    is_owner = "*" in actor_role.permissions
                    assignable = set(actor_role.permissions)
            self._check_permissions_assignable(permissions, assignable, owner=is_owner)
            role.permissions = permissions
        # An edited system role opts out of boot-time convergence — otherwise
        # the next restart would silently revert the change. The name stays.
        role.system = False
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="role",
            resource_id=role.id,
            action="role.updated",
            actor_user_id=actor.id if actor else None,
            details={"name": role.name, "permissions": role.permissions},
            ip_address=ip_address,
        )
        return role


def _slugify(name: str) -> str:
    slug = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
    return slug or f"ws-{uuid.uuid4().hex[:8]}"


def _chunks(ids: list[str], size: int = 500) -> list[list[str]]:
    """Split id lists so IN (...) stays under the SQLite 999-variable limit."""
    return [ids[i : i + size] for i in range(0, len(ids), size)]
