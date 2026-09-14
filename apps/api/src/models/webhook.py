"""Outbound webhook subscriptions and delivery attempts."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class WebhookSubscription(Base, TimestampMixin):
    """A subscriber URL for workspace domain events.

    The signing secret is kept in the SecretStore
    (`webhooks:<id>:signing_secret`), never in this row; the raw secret is
    returned once at creation/rotation only.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by_user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)


class WebhookDeliveryStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    EXHAUSTED = "exhausted"


class WebhookDelivery(Base, TimestampMixin):
    """One delivery attempt series for event × subscription (at-least-once).

    `status` transitions: pending → success | failed (retry scheduled via
    `next_retry_at`) → ... → exhausted after `MAX_ATTEMPTS` failures.
    """

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    subscription_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), default=WebhookDeliveryStatus.PENDING, index=True, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), index=True, nullable=True
    )
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = [
    "WebhookDelivery",
    "WebhookDeliveryStatus",
    "WebhookSubscription",
]
