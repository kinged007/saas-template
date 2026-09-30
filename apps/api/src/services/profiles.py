from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.security.password import PasswordHasher
from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.models.core import Invitation, Notification
from src.models.file_object import FileObject
from src.models.user_profile import UserProfile
from src.models.workspace import RefreshToken, Role, User, Workspace, WorkspaceMember
from src.services.files import purge_objects
from src.services.profile_helpers import (
    format_display_name,
    merge_custom_data,
)
from src.services.serializers import profile_to_dict
from src.storage.base import FileStorage

logger = logging.getLogger(__name__)


class ProfileService:
    def __init__(
        self,
        session: AsyncSession,
        bus: EventBus | None = None,
        storage: FileStorage | None = None,
    ) -> None:
        self._session = session
        self._bus = bus
        self._storage = storage

    async def get(self, user_id: str) -> UserProfile | None:
        return await self._session.get(UserProfile, user_id)

    async def get_or_create(self, user_id: str) -> UserProfile:
        stmt = select(UserProfile).where(UserProfile.user_id == user_id)
        result = await self._session.execute(stmt)
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing
        # Try insert; handle concurrent races via IntegrityError fallback
        profile = UserProfile(user_id=user_id, custom_data={})
        self._session.add(profile)
        try:
            await self._session.flush()
            await self._session.commit()
            await self._session.refresh(profile)
            return profile
        except IntegrityError:
            await self._session.rollback()
            result = await self._session.execute(stmt)
            existing = result.scalar_one_or_none()
            if existing is None:
                # Re-raise if still not found (unexpected)
                raise
            return existing

    async def update(
        self,
        user_id: str,
        data: dict[str, Any],
        is_put: bool,
        ip_address: str | None = None,
        actor_user_id: str | None = None,
    ) -> UserProfile:
        """
        Update profile. `data` is the validated payload dict (exclude_unset semantics
        handled by caller via model_dump(exclude_unset=True)). Handles custom_data
        merge/replace and common fields. Tracks changed_fields for audit.
        """
        profile = await self.get_or_create(user_id)
        user = await self._session.get(User, user_id)

        # Separate custom_data and avatar_url from common fields
        custom_patch = data.get("custom_data") if "custom_data" in data else None
        has_custom = "custom_data" in data
        avatar_url = data.get("avatar_url") if "avatar_url" in data else None
        has_avatar = "avatar_url" in data

        # Common fields list
        common_fields = [
            "first_name",
            "last_name",
            "bio",
            "phone_number",
            "timezone",
            "locale",
            "date_of_birth",
            "website_url",
            "location",
        ]

        changed_fields: list[str] = []

        # Handle avatar_url via User table
        if has_avatar and user is not None:
            # Normalize avatar_url: empty string -> None? Keep as provided
            new_avatar = avatar_url
            if new_avatar is not None:
                new_avatar = str(new_avatar)
            old_avatar = user.avatar_url
            if new_avatar != old_avatar:
                changed_fields.append("avatar_url")
                user.avatar_url = new_avatar

        # Handle common fields
        for field in common_fields:
            if field not in data:
                continue
            new_val = data[field]
            # Convert AnyHttpUrl to string for storage
            if field == "website_url" and new_val is not None:
                new_val = str(new_val)
            old_val = getattr(profile, field)
            # Normalize comparison for date vs string? direct compare
            if new_val != old_val:
                # Special handling: website_url AnyHttpUrl may have trailing slash differences?
                # Keep simple.
                changed_fields.append(field)
                setattr(profile, field, new_val)

        # Sync display_name from profile first/last (derived as "First L.")
        if user is not None and (
            "first_name" in changed_fields or "last_name" in changed_fields or not user.display_name
        ):
            new_display = format_display_name(
                profile.first_name, profile.last_name, user.display_name
            )
            if new_display and new_display != user.display_name:
                changed_fields.append("display_name")
                user.display_name = new_display

        # Handle custom_data
        if has_custom:
            # Merge or replace
            # need to handle case where custom_patch is None (explicit null?)
            # But schema defines custom_data as dict or None
            # If client sends {"custom_data": null} should we treat as replace
            # with {}? Probably not allowed; schema ensures dict if present
            # For PATCH null-delete case, patch contains dict with null values for deletion
            existing_data = profile.custom_data or {}
            # is_put semantics: if is_put and custom_patch is dict -> replace, else leave
            # For is_put False (PATCH), merge with null-delete
            try:
                merged = merge_custom_data(existing_data, custom_patch, is_put)
            except HTTPException:
                raise
            if merged != existing_data:
                # Determine which keys changed
                # Keys added/updated/deleted
                all_keys = set(existing_data.keys()) | set(merged.keys())
                for k in all_keys:
                    if existing_data.get(k) != merged.get(k):
                        # Check if key was deleted (in existing but not merged)
                        # or added/updated
                        changed_fields.append(f"custom_data.{k}")
                profile.custom_data = merged
                # Flag as modified for JSON column
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(profile, "custom_data")
            else:
                # Even if no change, ensure we still keep existing if PUT without custom_data?
                # No need
                pass

        # If no changed fields, still need to commit possible avatar changes? Already tracked
        # Publish audit if any change or even if none? Spec says every
        # PUT/PATCH publishes audit with changed_fields
        # We'll publish even if empty, but log.
        await self._session.flush()
        await self._session.commit()
        await self._session.refresh(profile)
        if user is not None and has_avatar:
            await self._session.refresh(user)

        # Publish audit (never include PII values, only keys)
        # Use actor_user_id = user_id (owner)
        actor = actor_user_id or user_id
        try:
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user_profile",
                resource_id=user_id,
                action="profile.updated",
                actor_user_id=actor,
                details={"changed_fields": sorted(changed_fields)},
                ip_address=ip_address,
            )
        except Exception:
            logger.exception("failed to publish audit for profile update %s", user_id)

        # Log without PII values
        logger.info("profile updated user_id=%s changed_fields=%s", user_id, changed_fields)

        return profile

    async def get_public_projection(
        self, target_user_id: str, viewer: User, *, is_deployment_admin: bool
    ) -> dict | None:
        """
        Returns redacted projection if viewer is co-member or deployment admin,
        else None. Caller should return 404 when None (to avoid enumeration).

        `is_deployment_admin` is passed in rather than read off `viewer`: the
        viewer may be an API key's creator, and a key never carries superuser
        power. The route derives it from `principal.is_deployment_admin`.
        """
        # Check target exists
        target_user = await self._session.get(User, target_user_id)
        if target_user is None:
            return None
        # Deployment-admin bypass
        if is_deployment_admin:
            pass
        else:
            if viewer.id == target_user_id:
                # Self is allowed via own profile endpoint, but for public
                # endpoint self also allowed
                pass
            else:
                # Check co-membership: share at least one active workspace
                viewer_stmt = select(WorkspaceMember.workspace_id).where(
                    WorkspaceMember.user_id == viewer.id, WorkspaceMember.status == "active"
                )
                v_result = await self._session.execute(viewer_stmt)
                viewer_wids = [row[0] for row in v_result.all()]
                if not viewer_wids:
                    return None
                target_stmt = (
                    select(WorkspaceMember.id)
                    .where(
                        WorkspaceMember.user_id == target_user_id,
                        WorkspaceMember.workspace_id.in_(viewer_wids),
                        WorkspaceMember.status == "active",
                    )
                    .limit(1)
                )
                t_result = await self._session.execute(target_stmt)
                if t_result.scalar_one_or_none() is None:
                    return None
        profile = await self.get_or_create(target_user_id)
        from src.services.serializers import public_projection

        return public_projection(profile, target_user)

    async def export_bundle(self, user_id: str) -> dict[str, Any]:
        user = await self._session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        profile = await self.get_or_create(user_id)
        # Workspaces memberships
        stmt = (
            select(Workspace, Role, WorkspaceMember)
            .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
            .join(Role, Role.id == WorkspaceMember.role_id)
            .where(WorkspaceMember.user_id == user_id, WorkspaceMember.status == "active")
        )
        result = await self._session.execute(stmt)
        rows = result.all()
        workspaces = []
        for w, role, member in rows:
            workspaces.append(
                {
                    "workspace_id": w.id,
                    "workspace_name": w.name,
                    "role": role.name if role else None,
                    "joined_at": member.created_at.isoformat() if member.created_at else None,
                }
            )
        # Counts
        audit_count_stmt = (
            select(func.count())
            .select_from(AuditLogEntry)
            .where(AuditLogEntry.actor_user_id == user_id)
        )
        audit_count = (await self._session.execute(audit_count_stmt)).scalar_one()
        notif_count_stmt = (
            select(func.count()).select_from(Notification).where(Notification.user_id == user_id)
        )
        notif_count = (await self._session.execute(notif_count_stmt)).scalar_one()

        from src.services.serializers import user_to_dict

        exported_at = datetime.now(UTC).isoformat()
        bundle = {
            "exported_at": exported_at,
            "user": user_to_dict(user),
            "profile": profile_to_dict(profile),
            "workspaces": workspaces,
            "counts": {"audit_entries": audit_count, "notifications": notif_count},
        }
        # Publish audit? Spec says export maybe publishes audit, but not required. We'll publish.
        try:
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user_id,
                action="user.exported",
                actor_user_id=user_id,
                details={"exported_at": exported_at},
            )
        except Exception:
            logger.exception("failed to publish export audit for %s", user_id)
        return bundle

    async def _file_storage_keys(self, user_id: str) -> list[str]:
        rows = await self._session.execute(
            select(FileObject.storage_key).where(FileObject.owner_user_id == user_id)
        )
        return list(rows.scalars())

    async def delete_account(
        self,
        user_id: str,
        confirm: str,
        password: str | None = None,
        ip_address: str | None = None,
        actor_user_id: str | None = None,
    ) -> None:
        if confirm != "DELETE":
            raise HTTPException(status_code=422, detail="confirm must be 'DELETE'")
        user = await self._session.get(User, user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="user not found")
        if user.password_hash is not None:
            if not password:
                raise HTTPException(status_code=422, detail="password required")
            if not PasswordHasher.verify(password, user.password_hash):
                raise HTTPException(status_code=403, detail="invalid password")
        # Publish audit before delete (retain email for trail)
        try:
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=user_id,
                action="user.deleted",
                actor_user_id=actor_user_id or user_id,
                details={"email": user.email},
                ip_address=ip_address,
            )
        except Exception:
            logger.exception("failed to publish delete audit for %s", user_id)

        # Also publish user.deleted event? Spec says publish user.deleted,
        # but event is audit.entry.created with action user.deleted
        # We already did.

        # Delete related rows
        # DRY: use delete statements
        file_keys = await self._file_storage_keys(user_id)
        await self._session.execute(delete(RefreshToken).where(RefreshToken.user_id == user_id))
        await self._session.execute(
            delete(WorkspaceMember).where(WorkspaceMember.user_id == user_id)
        )
        await self._session.execute(delete(Notification).where(Notification.user_id == user_id))
        await self._session.execute(delete(ApiKey).where(ApiKey.created_by_user_id == user_id))
        # Invitations where email matches user email (case-insensitive? email is stored lower)
        if user.email:
            await self._session.execute(
                delete(Invitation).where(Invitation.email == user.email.lower())
            )
            # Also where invited_by_user_id ?
            await self._session.execute(
                delete(Invitation).where(Invitation.invited_by_user_id == user_id)
            )
        # stored secrets? per workspace, not user, skip
        # Delete profile explicitly (FK cascade would handle, but explicit for sqlite)
        await self._session.execute(delete(UserProfile).where(UserProfile.user_id == user_id))
        await self._session.execute(delete(FileObject).where(FileObject.owner_user_id == user_id))
        # For conversations, handle participant cleanup: set user_id null?
        # But we can delete participations
        # Not required for MVP; leave.
        from src.models.conversation import ConversationParticipant

        # Remove conversation participants for this user
        try:
            await self._session.execute(
                delete(ConversationParticipant).where(ConversationParticipant.user_id == user_id)
            )
            await self._session.execute(
                delete(ConversationParticipant).where(
                    ConversationParticipant.participant_type == "user",
                    ConversationParticipant.participant_id == user_id,
                )
            )
        except Exception:
            # If table not exists or error, ignore
            pass

        # Finally delete user
        await self._session.delete(user)
        await self._session.commit()
        await purge_objects(self._storage, file_keys)
        logger.info("user deleted user_id=%s", user_id)

    async def delete_account_superuser(
        self, target_user_id: str, actor: User, ip_address: str | None = None
    ) -> None:
        if not actor.is_superuser:
            raise HTTPException(status_code=403, detail="superuser access required")
        target = await self._session.get(User, target_user_id)
        if target is None:
            raise HTTPException(status_code=404, detail="user not found")
        # Publish audit
        try:
            await publish_audit(
                self._bus,
                workspace_id=None,
                resource_type="user",
                resource_id=target_user_id,
                action="user.deleted",
                actor_user_id=actor.id,
                details={"email": target.email, "deleted_by_superuser": True},
                ip_address=ip_address,
            )
        except Exception:
            logger.exception("failed to publish superuser delete audit for %s", target_user_id)
        # Delete related rows same as above
        file_keys = await self._file_storage_keys(target_user_id)
        await self._session.execute(
            delete(RefreshToken).where(RefreshToken.user_id == target_user_id)
        )
        await self._session.execute(
            delete(WorkspaceMember).where(WorkspaceMember.user_id == target_user_id)
        )
        await self._session.execute(
            delete(Notification).where(Notification.user_id == target_user_id)
        )
        await self._session.execute(
            delete(ApiKey).where(ApiKey.created_by_user_id == target_user_id)
        )
        if target.email:
            await self._session.execute(
                delete(Invitation).where(Invitation.email == target.email.lower())
            )
            await self._session.execute(
                delete(Invitation).where(Invitation.invited_by_user_id == target_user_id)
            )
        await self._session.execute(
            delete(UserProfile).where(UserProfile.user_id == target_user_id)
        )
        await self._session.execute(
            delete(FileObject).where(FileObject.owner_user_id == target_user_id)
        )
        from src.models.conversation import ConversationParticipant

        try:
            await self._session.execute(
                delete(ConversationParticipant).where(
                    ConversationParticipant.user_id == target_user_id
                )
            )
            await self._session.execute(
                delete(ConversationParticipant).where(
                    ConversationParticipant.participant_type == "user",
                    ConversationParticipant.participant_id == target_user_id,
                )
            )
        except Exception:
            pass
        await self._session.delete(target)
        await self._session.commit()
        await purge_objects(self._storage, file_keys)
        logger.info("superuser deleted user_id=%s by %s", target_user_id, actor.id)
