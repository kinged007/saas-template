"""Uploaded-file metadata rows; bytes live in the storage backend."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class FileObject(Base, TimestampMixin):
    __tablename__ = "file_objects"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        StringUUID(), ForeignKey("workspaces.id", ondelete="CASCADE"), index=True, nullable=False
    )
    owner_user_id: Mapped[str] = mapped_column(
        StringUUID(), ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(127), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    # Uniquely keyed by the uuid4 prefix the service puts in front of the
    # filename; there is no unique index, so do not expect the database to
    # reject a duplicate here.
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
