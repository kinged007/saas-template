from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.dates import now_utc
from src.events.bus import EventBus
from src.events.publisher import publish_audit, publish_event
from src.events.subjects import Subjects
from src.models.conversation import Conversation, ConversationParticipant, Message
from src.models.workspace import User, Workspace, WorkspaceMember

logger = logging.getLogger(__name__)


class ConversationError(Exception):
    pass


class ConversationForbidden(ConversationError):
    pass


class ConversationNotFound(ConversationError):
    pass


def _truncate(text: str | None, max_len: int) -> str | None:
    if not text:
        return None
    t = text.strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


def _plain_preview(body: str) -> str:
    # Collapse whitespace, strip markdown-ish, truncate to 200.
    # Keep simple: strip and collapse newlines.
    text = " ".join(body.strip().split())
    return _truncate(text, 200) or ""


class ConversationService:
    def __init__(self, session: AsyncSession, bus: EventBus | None = None) -> None:
        self._session = session
        self._bus = bus

    # ---------------------------------------------------------------- helpers

    async def _ensure_membership(self, workspace_id: str, user_id: str) -> None:
        result = await self._session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == workspace_id,
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.status == "active",
            )
        )
        if result.scalar_one_or_none() is None:
            raise ConversationForbidden("you are not a member of this workspace")

    async def _get_participant(
        self, conversation_id: str, user_id: str
    ) -> ConversationParticipant | None:
        result = await self._session.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.participant_type == "user",
                ConversationParticipant.participant_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def _get_conversation(self, conversation_id: str) -> Conversation | None:
        return await self._session.get(Conversation, conversation_id)

    async def _participants_with_users(
        self, conversation_id: str
    ) -> list[tuple[ConversationParticipant, User | None]]:
        # Fetch participants plus user details (for type=user)
        result = await self._session.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id
            )
        )
        participants = list(result.scalars().all())
        user_ids = [p.participant_id for p in participants if p.participant_type == "user"]
        users: dict[str, User] = {}
        if user_ids:
            urows = await self._session.execute(select(User).where(User.id.in_(user_ids)))
            for u in urows.scalars().all():
                users[u.id] = u
        return [(p, users.get(p.participant_id) if p.participant_type == "user" else None) for p in participants]

    async def _unread_count(self, conversation_id: str, participant: ConversationParticipant) -> int:
        if participant.last_read_at is None:
            # Never read: count all messages in conversation
            result = await self._session.execute(
                select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
            )
            return int(result.scalar_one())
        # Count messages with created_at > last_read_at
        # Need to ensure UTC comparison; SQLite stores naive but we compare as stored.
        result = await self._session.execute(
            select(func.count())
            .select_from(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.created_at > participant.last_read_at,
            )
        )
        return int(result.scalar_one())

    async def _workspace_name(self, workspace_id: str) -> str | None:
        ws = await self._session.get(Workspace, workspace_id)
        return ws.name if ws else None

    def _conversation_to_dict(
        self,
        conv: Conversation,
        participants: list[tuple[ConversationParticipant, User | None]],
        unread_count: int,
        is_archived: bool,
        message_count: int | None = None,
    ) -> dict:
        part_list = []
        for p, u in participants:
            if p.participant_type == "user" and u:
                part_list.append(
                    {
                        "type": p.participant_type,
                        "id": p.participant_id,
                        "display_name": u.display_name,
                        "avatar_url": u.avatar_url,
                    }
                )
            else:
                part_list.append(
                    {
                        "type": p.participant_type,
                        "id": p.participant_id,
                        "display_name": p.participant_id,
                        "avatar_url": None,
                    }
                )
        data = {
            "id": conv.id,
            "workspace_id": conv.workspace_id,
            "title": conv.title,
            "created_by_user_id": conv.created_by_user_id,
            "last_message_at": conv.last_message_at.isoformat() if conv.last_message_at else None,
            "last_message_preview": conv.last_message_preview,
            "unread_count": unread_count,
            "is_archived": is_archived,
            "participants": part_list,
            "created_at": conv.created_at.isoformat() if conv.created_at else None,
            "updated_at": conv.updated_at.isoformat() if conv.updated_at else None,
        }
        if message_count is not None:
            data["message_count"] = message_count
        return data

    def _message_to_dict(self, msg: Message, sender_name: str | None = None, sender_avatar: str | None = None) -> dict:
        return {
            "id": msg.id,
            "conversation_id": msg.conversation_id,
            "sender_type": msg.sender_type,
            "sender_id": msg.sender_id,
            "sender_name": sender_name or msg.sender_id,
            "sender_avatar_url": sender_avatar,
            "body": msg.body,
            "body_html": msg.body_html,
            "created_at": msg.created_at.isoformat() if msg.created_at else None,
            "updated_at": msg.updated_at.isoformat() if msg.updated_at else None,
        }

    # ---------------------------------------------------------------- create

    async def create_conversation(
        self,
        *,
        workspace_id: str,
        creator: User,
        title: str | None,
        participant_user_ids: list[str],
        initial_message: str,
        ip_address: str | None = None,
    ) -> tuple[dict, dict]:
        # Basic validation
        body = initial_message.strip()
        if not body:
            raise ConversationError("initial message is required")
        if len(body) > 5000:
            raise ConversationError("initial message must be at most 5000 characters")
        if title is not None and len(title.strip()) > 300:
            raise ConversationError("title must be at most 300 characters")
        # Deduplicate participant_user_ids, remove creator if present (will re-add)
        others = []
        seen = set()
        for uid in participant_user_ids:
            uid = uid.strip()
            if not uid or uid in seen:
                continue
            if uid == creator.id:
                continue
            seen.add(uid)
            others.append(uid)

        # Need at least 1 other (so total >=2)
        if len(others) < 1:
            raise ConversationError("at least one other participant is required")
        total = len(others) + 1
        if total > 20:
            raise ConversationError("too many participants (max 20)")
        # Workspace membership check for creator
        await self._ensure_membership(workspace_id, creator.id)
        # Validate each other participant is active member
        if others:
            result = await self._session.execute(
                select(WorkspaceMember.user_id).where(
                    WorkspaceMember.workspace_id == workspace_id,
                    WorkspaceMember.user_id.in_(others),
                    WorkspaceMember.status == "active",
                )
            )
            found = {row[0] for row in result.all()}
            missing = set(others) - found
            if missing:
                raise ConversationError("one or more participants are not members of this workspace")

        # Resolve title
        clean_title = title.strip() if title and title.strip() else None
        if not clean_title:
            # Derive from participant names
            names = []
            if others:
                urows = await self._session.execute(select(User).where(User.id.in_(others)))
                id_to_name = {u.id: u.display_name for u in urows.scalars().all()}
                for uid in others:
                    names.append(id_to_name.get(uid, "Unknown"))
            if names:
                # Limit to 3 names
                if len(names) > 3:
                    clean_title = f"Chat with {', '.join(names[:3])} +{len(names)-3}"
                else:
                    clean_title = f"Chat with {', '.join(names)}"
            else:
                clean_title = _truncate(body, 80) or "New conversation"

        preview = _plain_preview(body)
        now = now_utc()

        conv = Conversation(
            workspace_id=workspace_id,
            created_by_user_id=creator.id,
            title=clean_title,
            last_message_at=now,
            last_message_preview=preview,
        )
        self._session.add(conv)
        await self._session.flush()  # get conv.id

        # Participants
        all_ids = [creator.id, *others]
        for uid in all_ids:
            is_creator = uid == creator.id
            p = ConversationParticipant(
                conversation_id=conv.id,
                participant_type="user",
                participant_id=uid,
                user_id=uid,
                agent_id=None,
                joined_at=now,
                last_read_at=now if is_creator else None,
                last_read_message_id=None,  # set after message
                archived_at=None,
            )
            self._session.add(p)

        msg = Message(
            conversation_id=conv.id,
            sender_type="user",
            sender_id=creator.id,
            sender_user_id=creator.id,
            sender_agent_id=None,
            body=body,
            body_html=None,
        )
        self._session.add(msg)
        await self._session.flush()

        # Update creator's last_read_message_id
        result = await self._session.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conv.id,
                ConversationParticipant.participant_id == creator.id,
                ConversationParticipant.participant_type == "user",
            )
        )
        creator_part = result.scalar_one()
        creator_part.last_read_message_id = msg.id

        await self._session.commit()

        # Fetch for serialization
        participants = await self._participants_with_users(conv.id)
        # After commit, conv is still attached; refresh if needed
        await self._session.refresh(conv)
        await self._session.refresh(msg)

        unread_for_creator = 0
        part_for_creator = next((p for p, _ in participants if p.participant_id == creator.id), None)
        is_arch = bool(part_for_creator.archived_at) if part_for_creator else False
        conv_dict = self._conversation_to_dict(conv, participants, unread_for_creator, is_arch, message_count=1)
        msg_dict = self._message_to_dict(msg, sender_name=creator.display_name, sender_avatar=creator.avatar_url)

        workspace_name = await self._workspace_name(workspace_id)

        # Publish durable event for notification pointers & realtime
        participant_ids = all_ids
        await publish_event(
            self._bus,
            Subjects.CONVERSATION_MESSAGE_CREATED,
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace_name or "workspace",
                "conversation_id": conv.id,
                "message_id": msg.id,
                "sender_id": creator.id,
                "sender_type": "user",
                "sender_name": creator.display_name,
                "body_preview": preview,
                "title": clean_title,
                "participant_user_ids": participant_ids,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="conversation",
            resource_id=conv.id,
            action="conversation.created",
            actor_user_id=creator.id,
            details={"title": clean_title, "participant_count": len(all_ids)},
            ip_address=ip_address,
        )
        # Also publish message created audit
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="message",
            resource_id=msg.id,
            action="message.created",
            actor_user_id=creator.id,
            details={"conversation_id": conv.id},
            ip_address=ip_address,
        )

        return conv_dict, msg_dict

    # ---------------------------------------------------------------- list

    async def list_conversations(
        self,
        *,
        workspace_id: str,
        user_id: str,
        archived: bool | None = False,
        q: str | None = None,
        offset: int = 0,
        limit: int = 20,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> tuple[list[dict], int]:
        await self._ensure_membership(workspace_id, user_id)

        # Base: conversations where user is participant and workspace matches
        # Join with participants
        base_stmt = (
            select(Conversation, ConversationParticipant)
            .join(
                ConversationParticipant,
                and_(
                    ConversationParticipant.conversation_id == Conversation.id,
                    ConversationParticipant.participant_type == "user",
                    ConversationParticipant.participant_id == user_id,
                ),
            )
            .where(Conversation.workspace_id == workspace_id)
        )
        if archived is True:
            base_stmt = base_stmt.where(ConversationParticipant.archived_at.is_not(None))
        elif archived is False:
            base_stmt = base_stmt.where(ConversationParticipant.archived_at.is_(None))
        # else None = no filter

        # Search handling
        if q:
            q_ilike = f"%{q.strip()}%"
            # Find conversation ids where participant display name matches
            sub_participant_match = (
                select(ConversationParticipant.conversation_id)
                .join(User, User.id == ConversationParticipant.user_id)
                .where(
                    ConversationParticipant.participant_type == "user",
                    User.display_name.ilike(q_ilike),
                )
            )
            # Title / preview matches
            base_stmt = base_stmt.where(
                or_(
                    Conversation.title.ilike(q_ilike),
                    Conversation.last_message_preview.ilike(q_ilike),
                    Conversation.id.in_(sub_participant_match),
                )
            )

        # Count total before pagination/sort
        count_stmt = select(func.count()).select_from(base_stmt.subquery())
        total_res = await self._session.execute(count_stmt)
        total = int(total_res.scalar_one())

        # Sorting
        if sort_by == "created_at":
            col = Conversation.created_at
        elif sort_by == "title":
            col = Conversation.title
        else:
            # default last_message_at desc
            col = Conversation.last_message_at
            sort_order = sort_order or "desc"
            # Ensure fallback order
        order = sort_order or "desc"
        if sort_by in ("created_at", "title", "last_message_at") or sort_by is None:
            if order == "desc":
                base_stmt = base_stmt.order_by(col.desc().nulls_last(), Conversation.created_at.desc())
            else:
                base_stmt = base_stmt.order_by(col.asc().nulls_first(), Conversation.created_at.asc())
        else:
            # Invalid sort, default
            base_stmt = base_stmt.order_by(Conversation.last_message_at.desc().nulls_last())

        base_stmt = base_stmt.offset(offset).limit(limit)
        rows = await self._session.execute(base_stmt)
        conv_parts = list(rows.all())

        results: list[dict] = []
        for conv, part in conv_parts:
            participants = await self._participants_with_users(conv.id)
            unread = await self._unread_count(conv.id, part)
            # Message count
            cnt = await self._session.execute(
                select(func.count()).select_from(Message).where(Message.conversation_id == conv.id)
            )
            mcount = int(cnt.scalar_one())
            is_arch = part.archived_at is not None
            results.append(self._conversation_to_dict(conv, participants, unread, is_arch, mcount))
        return results, total

    async def get_conversation(self, *, workspace_id: str, conversation_id: str, user_id: str) -> dict:
        await self._ensure_membership(workspace_id, user_id)
        conv = await self._get_conversation(conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise ConversationNotFound("conversation not found")
        part = await self._get_participant(conversation_id, user_id)
        if part is None:
            raise ConversationForbidden("you are not a participant of this conversation")
        participants = await self._participants_with_users(conversation_id)
        unread = await self._unread_count(conversation_id, part)
        cnt = await self._session.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
        )
        mcount = int(cnt.scalar_one())
        is_arch = part.archived_at is not None
        return self._conversation_to_dict(conv, participants, unread, is_arch, mcount)

    # ---------------------------------------------------------------- rename

    async def rename(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        title: str,
        actor_user_id: str | None = None,
        actor_agent_id: str | None = None,
        actor_type: Literal["user", "agent"] = "user",
        ip_address: str | None = None,
    ) -> dict:
        clean = title.strip() if title else ""
        if not clean or len(clean) > 300:
            raise ConversationError("title must be between 1 and 300 characters")
        conv = await self._get_conversation(conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise ConversationNotFound("conversation not found")
        # Permission check: if actor is user, must be participant and member
        if actor_type == "user":
            if not actor_user_id:
                raise ConversationError("actor_user_id required for user rename")
            await self._ensure_membership(workspace_id, actor_user_id)
            part = await self._get_participant(conversation_id, actor_user_id)
            if part is None:
                raise ConversationForbidden("you are not a participant of this conversation")
        else:
            # agent: allow if agent is participant OR system caller (no check for v1 except workspace match)
            # For future, check agent participant row exists if provided
            if actor_agent_id:
                result = await self._session.execute(
                    select(ConversationParticipant).where(
                        ConversationParticipant.conversation_id == conversation_id,
                        ConversationParticipant.participant_type == "agent",
                        ConversationParticipant.participant_id == actor_agent_id,
                    )
                )
                # If agent not participant, allow system rename but log
                if result.scalar_one_or_none() is None:
                    logger.info("agent %s renaming conversation %s without being participant", actor_agent_id, conversation_id)
        conv.title = clean
        await self._session.commit()
        await self._session.refresh(conv)
        # Audit
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="conversation",
            resource_id=conversation_id,
            action="conversation.renamed",
            actor_user_id=actor_user_id,
            details={"title": clean, "actor_type": actor_type, "actor_agent_id": actor_agent_id},
            ip_address=ip_address,
        )
        # Publish event for live title update (transient)
        await publish_event(
            self._bus,
            Subjects.CONVERSATION_RENAMED if hasattr(Subjects, "CONVERSATION_RENAMED") else Subjects.CONVERSATIONS + ".renamed",
            {
                "workspace_id": workspace_id,
                "conversation_id": conversation_id,
                "title": clean,
                "actor_user_id": actor_user_id,
                "actor_agent_id": actor_agent_id,
                "actor_type": actor_type,
            },
            transient=True,
        )
        # For return, need to compute dict with requester's view if user
        if actor_type == "user" and actor_user_id:
            part = await self._get_participant(conversation_id, actor_user_id)
            participants = await self._participants_with_users(conversation_id)
            unread = await self._unread_count(conversation_id, part) if part else 0
            is_arch = bool(part.archived_at) if part else False
            cnt = await self._session.execute(
                select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
            )
            mcount = int(cnt.scalar_one())
            return self._conversation_to_dict(conv, participants, unread, is_arch, mcount)
        # For agent, return minimal
        participants = await self._participants_with_users(conversation_id)
        # Use first participant to compute unread (not critical)
        first_part = participants[0][0] if participants else None
        unread = 0
        is_arch = False
        cnt = await self._session.execute(
            select(func.count()).select_from(Message).where(Message.conversation_id == conversation_id)
        )
        mcount = int(cnt.scalar_one())
        return self._conversation_to_dict(conv, participants, unread, is_arch, mcount)

    # ---------------------------------------------------------------- read / archive

    async def mark_read(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        user_id: str,
        last_read_message_id: str | None = None,
    ) -> dict:
        await self._ensure_membership(workspace_id, user_id)
        conv = await self._get_conversation(conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise ConversationNotFound("conversation not found")
        part = await self._get_participant(conversation_id, user_id)
        if part is None:
            raise ConversationForbidden("you are not a participant of this conversation")
        now = now_utc()
        part.last_read_at = now
        if last_read_message_id:
            # Validate message exists in conversation
            msg = await self._session.get(Message, last_read_message_id)
            if msg is None or msg.conversation_id != conversation_id:
                raise ConversationError("message not found in this conversation")
            part.last_read_message_id = last_read_message_id
        else:
            # Default to latest message id
            result = await self._session.execute(
                select(Message.id)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.created_at.desc())
                .limit(1)
            )
            latest = result.scalar_one_or_none()
            if latest:
                part.last_read_message_id = latest
        await self._session.commit()
        return {"success": True, "last_read_at": part.last_read_at.isoformat(), "last_read_message_id": part.last_read_message_id}

    async def set_archived(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        user_id: str,
        archived: bool,
    ) -> dict:
        await self._ensure_membership(workspace_id, user_id)
        conv = await self._get_conversation(conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise ConversationNotFound("conversation not found")
        part = await self._get_participant(conversation_id, user_id)
        if part is None:
            raise ConversationForbidden("you are not a participant of this conversation")
        if archived:
            part.archived_at = now_utc()
        else:
            part.archived_at = None
        await self._session.commit()
        return {"archived": archived, "archived_at": part.archived_at.isoformat() if part.archived_at else None}

    # ---------------------------------------------------------------- messages

    async def list_messages(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        user_id: str,
        offset: int = 0,
        limit: int = 50,
        sort_by: str = "created_at",
        sort_order: str = "asc",
    ) -> tuple[list[dict], int]:
        await self._ensure_membership(workspace_id, user_id)
        conv = await self._get_conversation(conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise ConversationNotFound("conversation not found")
        part = await self._get_participant(conversation_id, user_id)
        if part is None:
            raise ConversationForbidden("you are not a participant of this conversation")
        # Validate sort
        if sort_by not in ("created_at",):
            raise ConversationError("invalid sort field")
        stmt = select(Message).where(Message.conversation_id == conversation_id)
        count_res = await self._session.execute(select(func.count()).select_from(stmt.subquery()))
        total = int(count_res.scalar_one())
        if sort_order == "desc":
            stmt = stmt.order_by(Message.created_at.desc(), Message.id.desc())
        else:
            stmt = stmt.order_by(Message.created_at.asc(), Message.id.asc())
        stmt = stmt.offset(offset).limit(limit)
        rows = await self._session.execute(stmt)
        msgs = list(rows.scalars().all())
        # Fetch sender names
        sender_ids = {m.sender_id for m in msgs if m.sender_type == "user"}
        user_map: dict[str, User] = {}
        if sender_ids:
            urows = await self._session.execute(select(User).where(User.id.in_(sender_ids)))
            for u in urows.scalars().all():
                user_map[u.id] = u
        result = []
        for m in msgs:
            u = user_map.get(m.sender_id) if m.sender_type == "user" else None
            result.append(self._message_to_dict(m, sender_name=u.display_name if u else m.sender_id, sender_avatar=u.avatar_url if u else None))
        return result, total

    async def send_message(
        self,
        *,
        workspace_id: str,
        conversation_id: str,
        sender: User,
        body: str,
        ip_address: str | None = None,
    ) -> dict:
        clean = body.strip()
        if not clean:
            raise ConversationError("message body is required")
        if len(clean) > 5000:
            raise ConversationError("message must be at most 5000 characters")
        await self._ensure_membership(workspace_id, sender.id)
        conv = await self._get_conversation(conversation_id)
        if conv is None or conv.workspace_id != workspace_id:
            raise ConversationNotFound("conversation not found")
        part = await self._get_participant(conversation_id, sender.id)
        if part is None:
            raise ConversationForbidden("you are not a participant of this conversation")
        now = now_utc()
        preview = _plain_preview(clean)
        msg = Message(
            conversation_id=conversation_id,
            sender_type="user",
            sender_id=sender.id,
            sender_user_id=sender.id,
            sender_agent_id=None,
            body=clean,
            body_html=None,
        )
        self._session.add(msg)
        # Update conversation preview
        conv.last_message_at = now
        conv.last_message_preview = preview
        await self._session.flush()
        # Mark sender as read up to this message
        part.last_read_at = now
        part.last_read_message_id = msg.id
        await self._session.commit()
        await self._session.refresh(msg)

        workspace_name = await self._workspace_name(workspace_id)
        # Get all participant user ids
        result = await self._session.execute(
            select(ConversationParticipant.participant_id).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.participant_type == "user",
            )
        )
        participant_ids = [r[0] for r in result.all()]

        msg_dict = self._message_to_dict(msg, sender_name=sender.display_name, sender_avatar=sender.avatar_url)

        await publish_event(
            self._bus,
            Subjects.CONVERSATION_MESSAGE_CREATED,
            {
                "workspace_id": workspace_id,
                "workspace_name": workspace_name or "workspace",
                "conversation_id": conversation_id,
                "message_id": msg.id,
                "sender_id": sender.id,
                "sender_type": "user",
                "sender_name": sender.display_name,
                "body_preview": preview,
                "title": conv.title,
                "participant_user_ids": participant_ids,
                "body": clean,
            },
        )
        await publish_audit(
            self._bus,
            workspace_id=workspace_id,
            resource_type="message",
            resource_id=msg.id,
            action="message.created",
            actor_user_id=sender.id,
            details={"conversation_id": conversation_id},
            ip_address=ip_address,
        )
        return msg_dict

    # ---------------------------------------------------------------- unread count

    async def get_unread_counts(self, *, workspace_id: str, user_id: str) -> dict:
        await self._ensure_membership(workspace_id, user_id)
        # Active conversations only for count? Plan says count = sum unread across active conversations; unread_conversations = distinct with unread>0
        # But should exclude archived? Yes count only active.
        stmt = (
            select(Conversation, ConversationParticipant)
            .join(
                ConversationParticipant,
                and_(
                    ConversationParticipant.conversation_id == Conversation.id,
                    ConversationParticipant.participant_type == "user",
                    ConversationParticipant.participant_id == user_id,
                    ConversationParticipant.archived_at.is_(None),
                ),
            )
            .where(Conversation.workspace_id == workspace_id)
        )
        rows = await self._session.execute(stmt)
        total_count = 0
        unread_conversations = 0
        for conv, part in rows.all():
            unread = await self._unread_count(conv.id, part)
            if unread > 0:
                unread_conversations += 1
                total_count += unread
        # Also include archived? For badge sum we want only active? We'll keep active only for this method.
        return {"count": total_count, "unread_conversations": unread_conversations}

    async def get_unread_counts_all(self, *, workspace_id: str, user_id: str) -> dict:
        # Helper for tests: same as above but clearer name
        return await self.get_unread_counts(workspace_id=workspace_id, user_id=user_id)
