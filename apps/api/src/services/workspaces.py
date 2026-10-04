from __future__ import annotations

import secrets
import uuid
from datetime import timedelta

from sqlalchemy import delete, func, select
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
from src.models.workspace import (
    ACTIVE_MEMBERSHIP_STATUSES,
    MemberStatus,
    Role,
    User,
    Workspace,
    WorkspaceMember,
)
from src.services.auth import AuthService
from src.services.serializers import ONBOARDING_ENABLED_FLAG


class WorkspaceError(Exception):
    pass


class WorkspaceForbidden(WorkspaceError):
    pass


class WorkspaceConflict(WorkspaceError):
    pass


class WorkspaceNotFound(WorkspaceError):
    pass


# Which member statuses may take over a workspace, decided per status rather
# than by a `status != "active"` comparison that compiles against any status the
# domain gains later. Every `MemberStatus` has an entry, so a new one is refused
# until it is decided here; pinned by
# `test_transfer_eligibility_decides_every_member_status`. Mirrors
# `TRANSFER_ELIGIBLE` in `apps/web/src/pages/member-actions.ts`.
_TRANSFER_ELIGIBLE: dict[str, bool] = {
    MemberStatus.ACTIVE.value: True,
    MemberStatus.INVITED.value: False,
    MemberStatus.SUSPENDED.value: False,
}

# Same shape for the two member-status actions, for the same reason: a
# `== "suspended"` / `!= "suspended"` comparison compiles against any status
# the domain gains later, and each status gets its own decision here instead.
# `suspended` is `False` in `_SUSPEND_ALLOWED` to match the web table;
# `suspend_member` returns early on that status before consulting the table, so
# an idempotent no-op stays a 200 and an undecided status is refused instead of
# silently inheriting today's meaning. Mirrors `SUSPEND_ALLOWED` /
# `REACTIVATE_ALLOWED` in `apps/web/src/pages/member-actions.ts`; pinned by
# `test_suspend_and_reactivate_decide_every_member_status`.
_SUSPEND_ALLOWED: dict[str, bool] = {
    MemberStatus.ACTIVE.value: True,
    MemberStatus.INVITED.value: True,
    MemberStatus.SUSPENDED.value: False,
}

_REACTIVATE_ALLOWED: dict[str, bool] = {
    MemberStatus.ACTIVE.value: False,
    MemberStatus.INVITED.value: False,
    MemberStatus.SUSPENDED.value: True,
}


def is_owner_role_name(name: str | None) -> bool:
    """Whether a role name is the owner role, ignoring case.

    A workspace created before the case-insensitive name check (#328) can hold
    `Owner` beside the seeded `owner`, and that row was meant to be the owner
    role. Matched on the name rather than on `Role.system`: that flag is exactly
    what tells the legacy row apart, so requiring it would leave the row
    unprotected.

    The name is the whole signal, deliberately: `transfer_ownership` grants on
    this predicate alone, so a legacy `Owner` row an admin created pre-#328 —
    which carries no `"*"`, because `*` is reserved for the owner role — can
    still transfer ownership. Pinned by
    `test_legacy_owner_case_row_transfers_without_the_owner_permission`.

    The same hardening locks the row: `update_role` refuses it, `set_member_role`
    refuses both assigning it and taking it from a holder, `remove_member`,
    `leave_workspace` and `suspend_member` refuse the holder, and there is no
    role delete. #400's backfill is the only path that removes the row, so it has
    to reassign holders before dropping rows; #400 is parked on `needs-human`.
    """
    return (name or "").lower() == "owner"


def is_manager_role_name(name: str | None) -> bool:
    """Whether a role name may manage members: owner or admin, ignoring case.

    Both halves case-fold, and that is a widening, not a refactor: #624 replaced
    an exact `("owner", "admin")` comparison in `set_member_role` and
    `_require_manager`. A workspace created before the case-insensitive name
    check (#328) can hold a pre-#328 `Admin` row beside its seeded `admin`, and
    that row's holder is now admitted at both manager gates, where the exact
    comparison refused them. `_check_name_free` refuses the name
    case-insensitively, so such a row can only come from old data; #400's
    backfill is what removes it.

    Name-only by design, as on the owner half: an `Admin` row an admin created
    carries no `"*"`, since `"*"` is reserved for the owner role, and the gate
    admits it anyway. Pinned by
    `test_legacy_admin_case_row_counts_as_admin_at_the_manager_gates`; the owner
    half by
    `test_legacy_owner_case_row_counts_as_owner_for_transfer_and_manager_gates`.
    """
    lowered = (name or "").lower()
    return lowered == "admin" or is_owner_role_name(lowered)


class WorkspaceService:
    DEFAULT_ROLES = ["owner", "admin", "editor", "viewer"]

    # Fallback auto-join role for single-workspace mode (SINGLE_WORKSPACE).
    # Viewer: edit access requires explicit designation.
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
        everyone else joins as single_workspace_default_role. Existing
        members keep their role."""
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
        name = name.strip()
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
        onboarding_enabled: bool | None = None,
        actor: User | None = None,
        ip_address: str | None = None,
    ) -> Workspace:
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            raise WorkspaceError("workspace not found")
        changes: dict = {}
        if name is not None:
            name = name.strip()
        if name is not None and name != workspace.name:
            changes["name"] = {"from": workspace.name, "to": name}
            workspace.name = name
        if description is not None and description != workspace.description:
            changes["description"] = {"from": workspace.description, "to": description}
            workspace.description = description
        if onboarding_enabled is not None:
            # Stored in the flags JSON (FEATURE_FLAGS.md), default-on: a stored
            # True is dropped so the key never implies anything but "off".
            current = (workspace.flags or {}).get(ONBOARDING_ENABLED_FLAG) is not False
            if current != onboarding_enabled:
                changes[ONBOARDING_ENABLED_FLAG] = {
                    "from": current,
                    "to": onboarding_enabled,
                }
                flags = {
                    k: v for k, v in (workspace.flags or {}).items() if k != ONBOARDING_ENABLED_FLAG
                }
                if not onboarding_enabled:
                    flags[ONBOARDING_ENABLED_FLAG] = False
                workspace.flags = flags
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
            .where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.status.in_(ACTIVE_MEMBERSHIP_STATUSES),
            )
            .order_by(Workspace.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return list(result.all())

    async def get_workspace(self, workspace_id: str) -> Workspace | None:
        return await self._session.get(Workspace, workspace_id)

    async def get_membership(
        self, workspace_id: str, user_id: str, *, active_only: bool = True
    ) -> tuple[WorkspaceMember, Role] | None:
        """Resolve (member, role) for a user in a workspace.

        Defaults to active rows only, so a caller that forgets the flag cannot
        read a suspended member as active. A caller asking about the row itself
        rather than about access must pass `active_only=False`.
        """
        stmt = (
            select(WorkspaceMember, Role)
            .join(Role, Role.id == WorkspaceMember.role_id)
            .where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
            )
        )
        if active_only:
            stmt = stmt.where(WorkspaceMember.status.in_(ACTIVE_MEMBERSHIP_STATUSES))
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
        membership = await self.get_membership(workspace_id, actor.id, active_only=True)
        if membership is None:
            raise WorkspaceForbidden("you are not a member of this workspace")
        _, actor_role = membership
        if not is_manager_role_name(actor_role.name):
            raise WorkspaceForbidden("only the workspace owner or an admin can change roles")
        member = await self._session.get(WorkspaceMember, member_id)
        if member is None or member.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        current_role = await self._session.get(Role, member.role_id)
        if current_role is not None and is_owner_role_name(current_role.name):
            raise WorkspaceConflict("cannot change the workspace owner's role")
        role = await self._session.get(Role, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise WorkspaceError("role not found in workspace")
        if is_owner_role_name(role.name):
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
        if role and is_owner_role_name(role.name):
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

    async def leave_workspace(
        self,
        workspace_id: str,
        *,
        actor: User,
        ip_address: str | None = None,
    ) -> None:
        """Delete the actor's own membership. Owners cannot leave."""
        stmt = select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == actor.id,
            WorkspaceMember.status.in_(ACTIVE_MEMBERSHIP_STATUSES),
        )
        member = (await self._session.execute(stmt)).scalar_one_or_none()
        if member is None:
            raise WorkspaceError("membership not found")
        role = await self._session.get(Role, member.role_id)
        if role and is_owner_role_name(role.name):
            raise WorkspaceError("owners cannot leave the workspace")
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
                "user_id": actor.id,
                "removed_by_user_id": actor.id,
                "removed_by_name": actor.display_name,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="member",
            resource_id=member.id,
            action="member.left",
            actor_user_id=actor.id,
            details={"workspace_name": workspace_name},
            ip_address=ip_address,
        )

    async def _require_manager(
        self, workspace_id: str, actor: User
    ) -> tuple[WorkspaceMember, Role]:
        membership = await self.get_membership(workspace_id, actor.id, active_only=True)
        if membership is None:
            raise WorkspaceForbidden("you are not a member of this workspace")
        if not is_manager_role_name(membership[1].name):
            raise WorkspaceForbidden("only the workspace owner or an admin can manage members")
        return membership

    async def suspend_member(
        self,
        workspace_id: str,
        member_id: str,
        *,
        actor: User,
        ip_address: str | None = None,
    ) -> WorkspaceMember:
        await self._require_manager(workspace_id, actor)
        member = await self._session.get(WorkspaceMember, member_id)
        if member is None or member.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        if member.user_id == actor.id:
            raise WorkspaceConflict("cannot suspend yourself")
        role = await self._session.get(Role, member.role_id)
        if role is not None and is_owner_role_name(role.name):
            raise WorkspaceConflict("cannot suspend the workspace owner")
        if member.status == MemberStatus.SUSPENDED.value:
            return member
        if not _SUSPEND_ALLOWED.get(member.status, False):
            raise WorkspaceConflict("cannot suspend a member in this state")
        member.status = "suspended"
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="member",
            resource_id=member.id,
            action="member.suspended",
            actor_user_id=actor.id,
            details={"user_id": member.user_id},
            ip_address=ip_address,
        )
        return member

    async def reactivate_member(
        self,
        workspace_id: str,
        member_id: str,
        *,
        actor: User,
        ip_address: str | None = None,
    ) -> WorkspaceMember:
        await self._require_manager(workspace_id, actor)
        member = await self._session.get(WorkspaceMember, member_id)
        if member is None or member.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        if not _REACTIVATE_ALLOWED.get(member.status, False):
            raise WorkspaceConflict("member is not suspended")
        member.status = "active"
        await self._session.commit()
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="member",
            resource_id=member.id,
            action="member.reactivated",
            actor_user_id=actor.id,
            details={"user_id": member.user_id},
            ip_address=ip_address,
        )
        return member

    async def transfer_ownership(
        self,
        workspace_id: str,
        new_owner_membership_id: str,
        *,
        actor: User,
        ip_address: str | None = None,
    ) -> WorkspaceMember:
        membership = await self.get_membership(workspace_id, actor.id, active_only=True)
        if membership is None or not is_owner_role_name(membership[1].name):
            raise WorkspaceForbidden("only the workspace owner can transfer ownership")
        actor_member, _ = membership
        target = await self._session.get(WorkspaceMember, new_owner_membership_id)
        if target is None or target.workspace_id != workspace_id:
            raise WorkspaceError("member not found in workspace")
        if not _TRANSFER_ELIGIBLE.get(target.status, False):
            raise WorkspaceConflict("new owner must be an active member")
        if target.user_id == actor.id:
            raise WorkspaceConflict("you already own this workspace")
        owner_role = await self._role_by_name(workspace_id, "owner")
        admin_role = await self._role_by_name(workspace_id, "admin")
        target_role = await self._session.get(Role, target.role_id)
        target_previous_role = target_role.name if target_role is not None else None
        target.role_id = owner_role.id
        actor_member.role_id = admin_role.id
        await self._session.commit()

        workspace = await self._session.get(Workspace, workspace_id)
        workspace_name = workspace.name if workspace else "workspace"
        base = {
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "changed_by_user_id": actor.id,
            "changed_by_name": actor.display_name,
        }
        # The actor is the current owner (checked above), so both role changes
        # belong to a user: the promotion and the owner's own demotion.
        for user_id, from_role, to_role in (
            (target.user_id, target_previous_role, owner_role.name),
            (actor_member.user_id, owner_role.name, admin_role.name),
        ):
            await publish_event(
                self._bus,
                Subjects.WORKSPACE_MEMBER_ROLE_CHANGED,
                {**base, "user_id": user_id, "from_role": from_role, "to_role": to_role},
            )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="workspace",
            resource_id=workspace_id,
            action="workspace.ownership_transferred",
            actor_user_id=actor.id,
            details={"new_owner_user_id": target.user_id},
            ip_address=ip_address,
        )
        return target

    async def resend_invitation(
        self,
        workspace_id: str,
        invitation_id: str,
        *,
        actor: User,
        expires_in_hours: int = 72,
        ip_address: str | None = None,
    ) -> Invitation:
        await self._require_manager(workspace_id, actor)
        invite = await self._session.get(Invitation, invitation_id)
        if invite is None or invite.workspace_id != workspace_id:
            raise WorkspaceError("invitation not found")
        if invite.status in ("accepted", "revoked"):
            raise WorkspaceConflict(
                f"invitation is {invite.status} and cannot be re-sent; invite this address again"
            )
        if invite.status == "pending" and ensure_utc(invite.expires_at) >= now_utc():
            return invite
        invite.status = "pending"
        invite.token = secrets.token_urlsafe(32)
        invite.expires_at = now_utc() + timedelta(hours=expires_in_hours)
        invite.accepted_at = None
        await self._session.commit()
        workspace = await self._session.get(Workspace, workspace_id)
        role = await self._session.get(Role, invite.role_id)
        invited_by = await self._session.get(User, invite.invited_by_user_id)
        existing = await AuthService(self._session).get_by_email(invite.email)
        await publish_event(
            self._bus,
            Subjects.WORKSPACE_INVITATION_CREATED,
            {
                "invitation_id": invite.id,
                "workspace_id": workspace_id,
                "workspace_name": workspace.name if workspace else "workspace",
                "email": invite.email,
                "role": role.name if role else None,
                "invited_by_user_id": invite.invited_by_user_id,
                "invited_by_name": invited_by.display_name if invited_by else "",
                "is_registered": existing is not None,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="invitation",
            resource_id=invite.id,
            action="invitation.resent",
            actor_user_id=actor.id,
            details={"email": invite.email},
            ip_address=ip_address,
        )
        return invite

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
        if is_owner_role_name(role.name):
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

        # Fired for every invitation. The workflow emails unregistered
        # recipients; a failed send is audited (`invitation.email_failed`),
        # not raised. `resend` skips a still-pending, unexpired invitation, so
        # the audit entry is the signal to revoke the row and invite again.
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
        actor: User,
        ip_address: str | None = None,
    ) -> Invitation:
        await self._require_manager(workspace_id, actor)
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
            actor_user_id=actor.id,
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

    async def get_role(self, workspace_id: str, role_id: str) -> Role:
        role = await self._session.get(Role, role_id)
        if role is None or role.workspace_id != workspace_id:
            raise WorkspaceNotFound("role not found")
        return role

    async def _single_workspace_role(self, workspace_id: str) -> Role:
        """Auto-join role: SINGLE_WORKSPACE_DEFAULT_ROLE, else
        viewer/editor/admin/an arbitrary remaining non-owner role.

        Each rung is matched by name over the workspace's non-owner roles, so a
        custom role works too and an unknown, blank or "owner" value falls
        through the chain. The wider chain keeps a later login working when the
        viewer role was renamed or removed, instead of bricking every later
        login.

        Raises when the workspace has no non-owner role at all: there is
        nothing to join with, and the caller skips the join rather than
        granting owner. An owner-only workspace and one holding only a legacy
        owner-cased row both reach that, since is_owner_role_name drops those
        from the candidates."""
        from src.settings import settings

        result = await self._session.execute(select(Role).where(Role.workspace_id == workspace_id))
        roles = {role.name: role for role in result.scalars() if not is_owner_role_name(role.name)}
        names = (settings.single_workspace_default_role.strip(), self.SINGLE_WORKSPACE_ROLE)
        for name in (*names, "editor", "admin"):
            if role := roles.get(name):
                return role
        if roles:
            return next(iter(roles.values()))
        raise WorkspaceError(f"workspace {workspace_id} has no non-owner role to join")

    async def _role_by_name(self, workspace_id: str, name: str) -> Role:
        # Folded like the predicates its callers guard on, so a workspace whose
        # role rows predate #328 resolve through the same rule as the gate that
        # admits the caller. A legacy row can sit beside the seeded one, so an
        # exact-case row wins and the limit keeps the second row from turning the
        # lookup into a 500.
        stmt = (
            select(Role)
            .where(Role.workspace_id == workspace_id, func.lower(Role.name) == name.lower())
            .order_by(Role.name != name)
            .limit(1)
        )
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
        key_only = sorted(set(permissions) & set(KEY_ONLY_PERMISSIONS))
        if key_only:
            raise WorkspaceError(
                f"API-key-only permissions cannot be granted to roles: {', '.join(key_only)}"
            )
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
        # Case-insensitive: an "Admin" beside the seeded "admin" is a second,
        # indistinguishable row in listings and selects. `.first()`, not
        # `scalar_one_or_none()`: a workspace created before the case-insensitive
        # check can already hold such a pair, and the predicate then matches both.
        # The order is what makes the message deterministic: the system row
        # first, then oldest, then `id` — `created_at` is
        # `server_default=func.now()`, which ties on SQLite's second granularity,
        # so it cannot be the last key. System-first deliberately inverts the
        # "oldest first" preference in #592: the row a user needs named is the
        # seeded one, not whichever duplicate was written first.
        stmt = select(Role).where(
            Role.workspace_id == workspace_id, func.lower(Role.name) == name.lower()
        )
        if exclude_id is not None:
            stmt = stmt.where(Role.id != exclude_id)
        stmt = stmt.order_by(Role.system.desc(), Role.created_at, Role.id).limit(1)
        existing = (await self._session.execute(stmt)).scalars().first()
        if existing is not None:
            raise WorkspaceConflict(f"a role named '{existing.name}' already exists")

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
        name = name.strip()
        assignable: set[str] = set()
        is_owner = False
        if actor is not None:
            membership = await self.get_membership(workspace_id, actor.id, active_only=True)
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
        if name is not None:
            name = name.strip()
        role = await self.get_role(workspace_id, role_id)
        if is_owner_role_name(role.name):
            raise WorkspaceForbidden("the owner role cannot be edited")
        changed = False
        if name is not None and name != role.name:
            await self._check_name_free(workspace_id, name, exclude_id=role.id)
            role.name = name
            changed = True
        if description is not None and description != role.description:
            role.description = description
            changed = True
        if permissions is not None and sorted(permissions) != sorted(role.permissions or []):
            assignable: set[str] = set()
            is_owner = False
            if actor is not None:
                membership = await self.get_membership(workspace_id, actor.id, active_only=True)
                if membership is not None:
                    _, actor_role = membership
                    is_owner = "*" in actor_role.permissions
                    assignable = set(actor_role.permissions)
            self._check_permissions_assignable(permissions, assignable, owner=is_owner)
            role.permissions = permissions
            changed = True
        if not changed:
            return role
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
