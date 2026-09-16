from __future__ import annotations

from sqlalchemy import JSON, ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class UserTotpCredential(Base, TimestampMixin):
    """TOTP second factor for one user. `secret_ciphertext` is a versioned
    Fernet envelope (see SecretCipher); the raw secret never touches the DB.
    `backup_codes` holds sha256 hashes of single-use codes (removed on use).
    """

    __tablename__ = "user_totp_credentials"

    user_id: Mapped[str] = mapped_column(
        StringUUID(), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    secret_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    last_counter: Mapped[int | None] = mapped_column(Integer, nullable=True)
    backup_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
