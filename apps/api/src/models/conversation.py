from __future__ import annotations

import uuid

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    created_by_user_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False, default="chat", index=True)
    last_message_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_message_preview: Mapped[str | None] = mapped_column(String(200), nullable=True)


class ConversationParticipant(Base, TimestampMixin):
    __tablename__ = "conversation_participants"
    __table_args__ = (
        UniqueConstraint(
            "participant_type",
            "conversation_id",
            "participant_id",
            name="uq_conversation_participants_type_conversation_participant",
        ),
    )

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    participant_type: Mapped[str] = mapped_column(String(10), nullable=False, default="user", index=True)
    participant_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True, index=True)
    joined_at: Mapped[object] = mapped_column(DateTime(timezone=True), nullable=False)
    last_read_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_read_message_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    archived_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    agent_session_ref: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Message(Base, TimestampMixin):
    __tablename__ = "messages"
    __table_args__ = (
        Index("ix_messages_created_at", "created_at"),
        Index("ix_messages_conversation_id_created_at", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    conversation_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    sender_type: Mapped[str] = mapped_column(String(10), nullable=False, default="user")
    sender_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    sender_user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True, index=True)
    sender_agent_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    body_html: Mapped[str | None] = mapped_column(Text, nullable=True)
