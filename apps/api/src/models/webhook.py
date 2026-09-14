"""Outbound webhook subscriptions and delivery attempts.

A `WebhookSubscription` is a workspace-scoped callback URL with an event
filter. Each matching domain event fans out into one `WebhookDelivery` row
per subscription; deliveries retry with backoff until success or exhaustion.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from src.db.base import Base, StringUUID, TimestampMixin


class WebhookSubscription(Base, TimestampMixin):
    """One subscriber callback: URL + event filter for a workspace.

    The signing secret is NOT stored here — it lives in the `SecretStore`
    under `webhooks:<subscription_id>:signing_secret` so it benefits from
    encryption-at-rest, rotation, and future vault backends.
    """

    __tablename__ = "webhook_subscriptions"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False)
    # Subscribed public event names (see src.events.webhook_events); empty = all.
    events: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by_user_id: Mapped[str | None] = mapped_column(StringUUID(), nullable=True)

class WebhookDeliveryStatus:
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"  # terminally failed (exhausted retries) — see exhausted below
    EXHAUSTED = "exhausted"

class WebhookDelivery(Base, TimestampMixin):
    """One delivery attempt record: one event × one subscription."""

    __tablename__ = "webhook_deliveries"

    id: Mapped[str] = mapped_column(
        StringUUID(), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    subscription_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    workspace_id: Mapped[str] = mapped_column(StringUUID(), index=True, nullable=False)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    subject: Mapped[str] = mapped_column(String(100), nullable=False)
    # v1 envelope {event, event_id, occurred_at, workspace_id, data}.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(
        String(20), default=WebhookDeliveryStatus.PENDING, index=True, nullable=False
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Next retry eligible time (UTC). NULL once terminal (success/exhausted).
    next_retry_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_attempt_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

__all__ = [
    "WebhookDelivery",
    "WebhookDeliveryStatus",
    "WebhookSubscription",
]
