"""Workspace-scoped search and data export.

Search is DB LIKE/ILIKE first (no extra dependency, works on sqlite and
postgres). ponytail: ceiling is pg_trgm/GIN or a dedicated engine
(meilisearch/typesense) when result ranking or scale outgrows ILIKE; the
per-type result shape here ({type,id,title,snippet}) already matches what a
ranked engine would return, so only the query layer needs swapping.
"""

from __future__ import annotations

import csv
import io
import json
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.permissions import JOB_READ
from src.events.bus import EventBus
from src.events.publisher import publish_audit
from src.models.api_key import ApiKey
from src.models.audit import AuditLogEntry
from src.models.conversation import Conversation, ConversationParticipant, Message
from src.models.core import Invitation, Notification
from src.models.jobs import JobDefinition
from src.models.user_profile import UserProfile
from src.models.webhook import WebhookSubscription
from src.models.workspace import Role, User, Workspace, WorkspaceMember
from src.services.jobs import _mask_params
from src.services.profile_helpers import escape_like
from src.services.serializers import (
    notification_to_dict,
    public_projection,
    user_to_dict,
    workspace_to_dict,
)

# (resource label, per-query row cap)
_SEARCH_LIMIT = 5

# Export row caps: the bundle is one in-memory JSON string, so messages and
# notifications (the unbounded sections) are capped. ponytail: stream the
# response or paginate per conversation when workspaces outgrow these caps.
_EXPORT_MESSAGES_CAP = 5000
_EXPORT_NOTIFICATIONS_CAP = 5000


_EXPORT_AUDIT_CAP = 5000


# Profile fields mirrored into the members CSV. Prefixed because the profile
# projection also carries display_name/email/avatar_url, which would otherwise
# shadow the user columns. phone_number and date_of_birth are left out: the
# projection redacts both, and a permanently empty column reads as data loss.
_MEMBER_PROFILE_COLUMNS = [
    "first_name",
    "last_name",
    "bio",
    "timezone",
    "locale",
    "website_url",
    "location",
    "custom_data",
]

# resource -> tabular CSV columns for ?format=csv&resource=<name>
# Single source of truth: GET /workspaces/export/resources serves these keys so
# the frontend selector never carries its own copy of the list.
CSV_RESOURCES: dict[str, list[str]] = {
    "members": [
        "id",
        "email",
        "display_name",
        "avatar_url",
        "email_verified",
        "role",
        "status",
        "joined_at",
    ]
    + [f"profile_{c}" for c in _MEMBER_PROFILE_COLUMNS],
    "invitations": ["email", "status", "expires_at", "created_at"],
    "api_keys": ["name", "key_prefix", "permissions", "revoked_at", "created_at"],
    "jobs": ["key", "name", "enabled", "cron_schedule", "next_run_at"],
    "conversations": ["title", "last_message_preview", "last_message_at", "created_at"],
    "notifications": ["type", "title", "acknowledged_at", "created_at"],
    "audit": [
        "id",
        "created_at",
        "actor_email",
        "action",
        "resource_type",
        "resource_id",
        "ip_address",
    ],
}


def _snippet(text: str | None, q: str, width: int = 120) -> str | None:
    if not text:
        return None
    low = text.lower()
    idx = low.find(q.lower())
    if idx == -1:
        text = text.strip()
        return text[:width] + ("…" if len(text) > width else "")
    start = max(0, idx - 40)
    end = min(len(text), idx + len(q) + 40)
    frag = text[start:end].strip()
    return ("…" if start > 0 else "") + frag + ("…" if end < len(text) else "")


async def _ensure_membership(session: AsyncSession, workspace_id: str, user_id: str) -> None:
    from src.services.conversations import ConversationForbidden

    result = await session.execute(
        select(WorkspaceMember).where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            WorkspaceMember.status == "active",
        )
    )
    if result.scalar_one_or_none() is None:
        raise ConversationForbidden("you are not a member of this workspace")


# Excel and LibreOffice evaluate a cell starting with one of these as a formula
# on open, so an exported name or email runs on whoever opens the file. TAB, CR
# and LF start a formula too: the spreadsheet drops the control character and
# reads the formula behind it. The full-width forms are the same characters from
# a CJK IME, which produces them while the user types an ASCII payload. The "'"
# prefix is a convention, not a guarantee — Excel can strip it on
# save-and-reopen, so an edited file can reactivate.
_CSV_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n", "＝", "＋", "－", "＠")


def _csv_cell(value: object) -> object:
    """Encode one CSV cell: structured values as JSON, formulas defused."""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    if isinstance(value, str) and value.startswith(_CSV_FORMULA_PREFIXES):
        return "'" + value
    return value


class SearchExportService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    async def search(self, *, workspace_id: str, user_id: str, q: str) -> dict:
        await _ensure_membership(self._session, workspace_id, user_id)
        like = f"%{escape_like(q.strip())}%"
        can_view_jobs = await self._can(workspace_id, user_id, JOB_READ)
        results: list[dict] = []

        conv_rows = (
            (
                await self._session.execute(
                    select(Conversation)
                    .join(
                        ConversationParticipant,
                        (ConversationParticipant.conversation_id == Conversation.id)
                        & (ConversationParticipant.participant_type == "user")
                        & (ConversationParticipant.participant_id == user_id),
                    )
                    .where(
                        Conversation.workspace_id == workspace_id,
                        or_(
                            Conversation.title.ilike(like, escape="\\"),
                            Conversation.last_message_preview.ilike(like, escape="\\"),
                        ),
                    )
                    .limit(_SEARCH_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        for c in conv_rows:
            results.append(
                {
                    "type": "conversation",
                    "id": c.id,
                    "title": c.title,
                    "snippet": _snippet(c.last_message_preview, q),
                }
            )

        msg_rows = (
            await self._session.execute(
                select(Message, Conversation.title)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .join(
                    ConversationParticipant,
                    (ConversationParticipant.conversation_id == Conversation.id)
                    & (ConversationParticipant.participant_type == "user")
                    & (ConversationParticipant.participant_id == user_id),
                )
                .where(
                    Conversation.workspace_id == workspace_id,
                    Message.body.ilike(like, escape="\\"),
                )
                .order_by(Message.created_at.desc())
                .limit(_SEARCH_LIMIT)
            )
        ).all()
        for m, title in msg_rows:
            results.append(
                {
                    "type": "message",
                    "id": m.id,
                    "title": title,
                    "snippet": _snippet(m.body, q),
                    "conversation_id": m.conversation_id,
                }
            )

        member_rows = (
            await self._session.execute(
                select(User, Role.name, WorkspaceMember, UserProfile)
                .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
                .join(Role, Role.id == WorkspaceMember.role_id)
                .outerjoin(UserProfile, UserProfile.user_id == User.id)
                .where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.status == "active",
                    or_(
                        User.email.ilike(like, escape="\\"),
                        User.display_name.ilike(like, escape="\\"),
                        UserProfile.first_name.ilike(like, escape="\\"),
                        UserProfile.last_name.ilike(like, escape="\\"),
                    ),
                )
                .limit(_SEARCH_LIMIT)
            )
        ).all()
        for u, role_name, _m, p in member_rows:
            entry: dict = {"type": "member", "id": u.id}
            if p is not None:
                proj = public_projection(p, u)
                entry["title"] = proj.get("display_name") or u.display_name
            else:
                entry["title"] = u.display_name
            entry["snippet"] = f"{u.email} · {role_name}"
            results.append(entry)

        job_rows: list = []
        if can_view_jobs:
            job_rows = (
                (
                    await self._session.execute(
                        select(JobDefinition)
                        .where(
                            JobDefinition.workspace_id == workspace_id,
                            or_(
                                JobDefinition.name.ilike(like, escape="\\"),
                                JobDefinition.key.ilike(like, escape="\\"),
                                JobDefinition.description.ilike(like, escape="\\"),
                            ),
                        )
                        .limit(_SEARCH_LIMIT)
                    )
                )
                .scalars()
                .all()
            )
        for j in job_rows:
            results.append(
                {
                    "type": "job",
                    "id": j.id,
                    "title": j.name,
                    "snippet": _snippet(j.description or j.key, q),
                }
            )

        notif_rows = (
            (
                await self._session.execute(
                    select(Notification)
                    .where(
                        Notification.workspace_id == workspace_id,
                        Notification.user_id == user_id,
                        or_(
                            Notification.title.ilike(like, escape="\\"),
                            Notification.body.ilike(like, escape="\\"),
                        ),
                    )
                    .limit(_SEARCH_LIMIT)
                )
            )
            .scalars()
            .all()
        )
        for n in notif_rows:
            results.append(
                {
                    "type": "notification",
                    "id": n.id,
                    "title": n.title,
                    "snippet": _snippet(n.body, q),
                }
            )

        return {"query": q, "results": results}

    async def _can(self, workspace_id: str, user_id: str, permission: str) -> bool:
        from src.services.workspaces import WorkspaceService

        membership = await WorkspaceService(self._session).get_membership(workspace_id, user_id)
        if membership is None:
            return False
        _, role = membership
        return "*" in (role.permissions or []) or permission in (role.permissions or [])

    async def export_json(self, *, workspace_id: str, user_id: str) -> dict:
        """Full-workspace dump for data portability.

        Broader than search by design: includes all conversations/messages
        and all users' notifications regardless of the exporter's own
        participation. Caller must hold audit:read (owner/admin-only). Do not
        lower the route permission without revisiting this semantic.
        """
        workspace = await self._session.get(Workspace, workspace_id)
        if workspace is None:
            from fastapi import HTTPException

            raise HTTPException(status_code=404, detail="workspace not found")
        await _ensure_membership(self._session, workspace_id, user_id)

        member_rows = (
            await self._session.execute(
                select(WorkspaceMember, User, Role, UserProfile)
                .join(User, User.id == WorkspaceMember.user_id)
                .join(Role, Role.id == WorkspaceMember.role_id)
                .outerjoin(UserProfile, UserProfile.user_id == User.id)
                .where(WorkspaceMember.workspace_id == workspace_id)
            )
        ).all()
        members = []
        for m, u, r, p in member_rows:
            entry = user_to_dict(u)
            entry.pop("is_superuser", None)
            entry.update(
                {
                    "membership_id": m.id,
                    "role": r.name,
                    "status": m.status,
                    "joined_at": m.created_at.isoformat() if m.created_at else None,
                }
            )
            # Key stays present even without a profile row, so importers see a
            # uniform member shape.
            entry["profile"] = public_projection(p, u) if p is not None else None
            members.append(entry)

        roles = (
            (await self._session.execute(select(Role).where(Role.workspace_id == workspace_id)))
            .scalars()
            .all()
        )
        invites = (
            (
                await self._session.execute(
                    select(Invitation).where(Invitation.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        keys = (
            (await self._session.execute(select(ApiKey).where(ApiKey.workspace_id == workspace_id)))
            .scalars()
            .all()
        )
        jobs = (
            (
                await self._session.execute(
                    select(JobDefinition).where(JobDefinition.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        convs = (
            (
                await self._session.execute(
                    select(Conversation).where(Conversation.workspace_id == workspace_id)
                )
            )
            .scalars()
            .all()
        )
        conv_ids = [c.id for c in convs]
        messages: list[Message] = []
        truncated = False
        if conv_ids:
            messages = (
                (
                    await self._session.execute(
                        select(Message)
                        .where(Message.conversation_id.in_(conv_ids))
                        .order_by(Message.created_at.asc())
                        .limit(_EXPORT_MESSAGES_CAP + 1)
                    )
                )
                .scalars()
                .all()
            )
            if len(messages) > _EXPORT_MESSAGES_CAP:
                messages = messages[:_EXPORT_MESSAGES_CAP]
                truncated = True
        notifs = (
            (
                await self._session.execute(
                    select(Notification)
                    .where(Notification.workspace_id == workspace_id)
                    .limit(_EXPORT_NOTIFICATIONS_CAP + 1)
                )
            )
            .scalars()
            .all()
        )
        if len(notifs) > _EXPORT_NOTIFICATIONS_CAP:
            notifs = notifs[:_EXPORT_NOTIFICATIONS_CAP]
            truncated = True
        audit_rows = (
            await self._session.execute(
                select(AuditLogEntry, User.email)
                .outerjoin(User, User.id == AuditLogEntry.actor_user_id)
                .where(AuditLogEntry.workspace_id == workspace_id)
                .order_by(AuditLogEntry.created_at.asc())
                .limit(_EXPORT_AUDIT_CAP + 1)
            )
        ).all()
        if len(audit_rows) > _EXPORT_AUDIT_CAP:
            audit_rows = audit_rows[:_EXPORT_AUDIT_CAP]
            truncated = True
        subs = (
            (
                await self._session.execute(
                    select(WebhookSubscription).where(
                        WebhookSubscription.workspace_id == workspace_id
                    )
                )
            )
            .scalars()
            .all()
        )

        exported_at = datetime.now(UTC).isoformat()
        bundle = {
            "exported_at": exported_at,
            "truncated": truncated,
            "workspace": workspace_to_dict(workspace),
            "members": members,
            "roles": [
                {
                    "name": r.name,
                    "description": r.description,
                    "permissions": r.permissions,
                    "system": r.system,
                }
                for r in roles
            ],
            "invitations": [
                {
                    "email": i.email,
                    "status": i.status,
                    "expires_at": i.expires_at.isoformat() if i.expires_at else None,
                    "created_at": i.created_at.isoformat() if i.created_at else None,
                }
                for i in invites
            ],
            # Secrets never leave the server: key hashes and webhook signing
            # secrets stay out; the shape still imports cleanly (names +
            # permissions re-mint on import).
            "api_keys": [
                {
                    "name": k.name,
                    "key_prefix": k.key_prefix,
                    "permissions": k.permissions,
                    "revoked_at": k.revoked_at.isoformat() if k.revoked_at else None,
                    "created_at": k.created_at.isoformat() if k.created_at else None,
                }
                for k in keys
            ],
            "jobs": [
                {
                    "key": j.key,
                    "name": j.name,
                    "description": j.description,
                    "cron_schedule": j.cron_schedule,
                    "params": _mask_params(j.params_schema or {}, j.params or {}),
                    "enabled": j.enabled,
                    "next_run_at": j.next_run_at.isoformat() if j.next_run_at else None,
                }
                for j in jobs
            ],
            "conversations": [
                {
                    "id": c.id,
                    "title": c.title,
                    "created_by_user_id": c.created_by_user_id,
                    "last_message_at": c.last_message_at.isoformat() if c.last_message_at else None,
                    "last_message_preview": c.last_message_preview,
                    "created_at": c.created_at.isoformat() if c.created_at else None,
                }
                for c in convs
            ],
            "messages": [
                {
                    "id": m.id,
                    "conversation_id": m.conversation_id,
                    "sender_type": m.sender_type,
                    "sender_id": m.sender_id,
                    "body": m.body,
                    "created_at": m.created_at.isoformat() if m.created_at else None,
                }
                for m in messages
            ],
            "notifications": [notification_to_dict(n) for n in notifs],
            "audit": [
                {
                    "id": e.id,
                    "actor_user_id": e.actor_user_id,
                    "actor_email": email,
                    "resource_type": e.resource_type,
                    "resource_id": e.resource_id,
                    "action": e.action,
                    # `details` is already readable through GET /audit by anyone
                    # holding audit:read, which gates this export too.
                    "details": e.details,
                    "ip_address": e.ip_address,
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
                for e, email in audit_rows
            ],
            "webhook_subscriptions": [
                {"url": s.url, "events": s.events or [], "active": s.active} for s in subs
            ],
        }
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="workspace",
            resource_id=workspace_id,
            action="workspace.exported",
            actor_user_id=user_id,
            details={"exported_at": exported_at},
        )
        return bundle

    @staticmethod
    def export_csv(bundle: dict, resource: str) -> str:
        columns = CSV_RESOURCES.get(resource)
        if columns is None:
            raise ValueError(
                f"unknown resource: {resource} (choose from {', '.join(sorted(CSV_RESOURCES))})"
            )
        rows = bundle.get(resource, [])
        if resource == "members":
            flat = [
                {
                    "id": r.get("id"),
                    "email": r.get("email"),
                    "display_name": r.get("display_name"),
                    "avatar_url": r.get("avatar_url"),
                    "email_verified": r.get("email_verified"),
                    "role": r.get("role"),
                    "status": r.get("status"),
                    "joined_at": r.get("joined_at"),
                    # Read back from the bundle, so the CSV carries exactly what
                    # the JSON export carries: the redacted public projection,
                    # and empty cells when the member has no profile row.
                    **{
                        f"profile_{c}": (r.get("profile") or {}).get(c)
                        for c in _MEMBER_PROFILE_COLUMNS
                    },
                }
                for r in rows
            ]
        elif resource == "api_keys":
            flat = [
                {
                    "name": r.get("name"),
                    "key_prefix": r.get("key_prefix"),
                    "permissions": ";".join(r.get("permissions") or []),
                    "revoked_at": r.get("revoked_at"),
                    "created_at": r.get("created_at"),
                }
                for r in rows
            ]
        elif resource == "jobs":
            flat = [
                {
                    "key": r.get("key"),
                    "name": r.get("name"),
                    "enabled": r.get("enabled"),
                    "cron_schedule": r.get("cron_schedule"),
                    "next_run_at": r.get("next_run_at"),
                }
                for r in rows
            ]
        elif resource == "conversations":
            flat = [
                {
                    "title": r.get("title"),
                    "last_message_preview": r.get("last_message_preview"),
                    "last_message_at": r.get("last_message_at"),
                    "created_at": r.get("created_at"),
                }
                for r in rows
            ]
        elif resource == "notifications":
            flat = [
                {
                    "type": r.get("type"),
                    "title": r.get("title"),
                    "acknowledged_at": r.get("acknowledged_at"),
                    "created_at": r.get("created_at"),
                }
                for r in rows
            ]
        elif resource == "audit":
            flat = [
                {
                    "id": r.get("id"),
                    "created_at": r.get("created_at"),
                    "actor_email": r.get("actor_email"),
                    "action": r.get("action"),
                    "resource_type": r.get("resource_type"),
                    "resource_id": r.get("resource_id"),
                    "ip_address": r.get("ip_address"),
                }
                for r in rows
            ]
        else:  # invitations
            flat = [
                {
                    "email": r.get("email"),
                    "status": r.get("status"),
                    "expires_at": r.get("expires_at"),
                    "created_at": r.get("created_at"),
                }
                for r in rows
            ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=columns)
        writer.writeheader()
        # DictWriter raises on a key the columns do not declare, but writes an
        # empty cell for a column the projection does not produce, so that drift
        # ships as a blank column. One row is enough: every row of a resource
        # comes from the same projection arm.
        if flat and set(flat[0]) != set(columns):
            raise ValueError(
                f"{resource} projection and columns differ: {sorted(set(columns) ^ set(flat[0]))}"
            )
        # One choke point, so a new resource is covered by construction.
        writer.writerows({k: _csv_cell(v) for k, v in row.items()} for row in flat)
        return buf.getvalue()
