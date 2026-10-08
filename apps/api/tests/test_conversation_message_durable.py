"""Tests: the durable message.created consumer and the participant_user_ids normalizer.

The durable consumer persists notification pointers from
`participant_user_ids`. A malformed payload must be rejected (no rows
written); a valid list must produce one pointer per non-sender recipient,
deduped in first-seen order. The tail covers the shared normalizer
(`_participant_user_ids`) directly: absent / None / empty list / bare
string / non-string, empty, or whitespace-only items / dict payload /
dedupe + order, plus the malformed-field warning (#1514).
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select

from src.db.session import SessionFactory
from src.events.bus import EventMetadata
from src.events.factory import WorkflowRegistry
from src.events.subjects import Subjects
from src.models.core import Notification
from src.workflows import _participant_user_ids, build_workflows


class _NoopBus:
    async def subscribe(self, subject, handler, *, fanout=False):
        return f"{subject}:sub"

    async def unsubscribe(self, subscription_id) -> None:
        return None

    async def publish(self, subject, payload, *, correlation_id=None, transient=False) -> None:
        return None

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None


def _wired() -> tuple:
    bus = _NoopBus()
    registry = WorkflowRegistry(bus)
    build_workflows(registry, bus, connection_manager=None)
    handler = registry._entries[Subjects.CONVERSATION_MESSAGE_CREATED][0]
    return handler


async def _notification_user_ids() -> list[str]:
    async with SessionFactory() as session:
        result = await session.execute(select(Notification.user_id))
        return sorted(r[0] for r in result.all())


async def test_durable_message_creates_pointer_per_non_sender_recipient():
    handler = _wired()
    sender, recipient_a, recipient_b = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    await handler(
        {
            "workspace_id": str(uuid.uuid4()),
            "conversation_id": str(uuid.uuid4()),
            "message_id": str(uuid.uuid4()),
            "sender_id": sender,
            "sender_type": "user",
            "participant_user_ids": [recipient_b, sender, recipient_a, sender],
        },
        EventMetadata(subject=Subjects.CONVERSATION_MESSAGE_CREATED),
    )

    assert await _notification_user_ids() == sorted([recipient_a, recipient_b])


async def test_durable_message_malformed_participants_write_nothing():
    handler = _wired()
    for malformed in ("u1", ["u1", 42], ["u1", ""], ["u1", " "], {"a": "b"}, 42):
        await handler(
            {
                "workspace_id": str(uuid.uuid4()),
                "conversation_id": str(uuid.uuid4()),
                "sender_id": str(uuid.uuid4()),
                "participant_user_ids": malformed,
            },
            EventMetadata(subject=Subjects.CONVERSATION_MESSAGE_CREATED),
        )

    assert await _notification_user_ids() == []


async def test_durable_message_malformed_participants_logs_warning(caplog):
    """A present-but-malformed field logs a warning carrying the event's
    subject and correlation_id so a publisher regression is diagnosable."""
    handler = _wired()
    with caplog.at_level(logging.WARNING, logger="src.workflows"):
        await handler(
            {
                "workspace_id": str(uuid.uuid4()),
                "conversation_id": str(uuid.uuid4()),
                "sender_id": str(uuid.uuid4()),
                "participant_user_ids": "u1",
            },
            EventMetadata(
                subject=Subjects.CONVERSATION_MESSAGE_CREATED, correlation_id="corr-1514"
            ),
        )

    warnings = [r for r in caplog.records if "malformed participant_user_ids" in r.getMessage()]
    assert len(warnings) == 1
    assert "conversations.message.created" in warnings[0].getMessage()
    assert "corr-1514" in warnings[0].getMessage()


def test_participant_user_ids_normalizer():
    assert _participant_user_ids({}) is None
    assert _participant_user_ids({"participant_user_ids": None}) is None
    assert _participant_user_ids({"participant_user_ids": []}) == []
    assert _participant_user_ids({"participant_user_ids": "u1"}) is None
    assert _participant_user_ids({"participant_user_ids": 42}) is None
    assert _participant_user_ids({"participant_user_ids": {"a": "b"}}) is None
    assert _participant_user_ids({"participant_user_ids": ["u1", 42]}) is None
    assert _participant_user_ids({"participant_user_ids": ["u1", ""]}) is None
    assert _participant_user_ids({"participant_user_ids": ["u1", " "]}) is None
    assert _participant_user_ids({"participant_user_ids": ["\t", "\n"]}) is None
    assert _participant_user_ids({"participant_user_ids": ["u2", "u1", "u2"]}) == ["u2", "u1"]


def test_participant_user_ids_malformed_logs_warning(caplog):
    with caplog.at_level(logging.WARNING, logger="src.workflows"):
        assert (
            _participant_user_ids(
                {"participant_user_ids": "u1"}, subject="subj.x", correlation_id="corr-1"
            )
            is None
        )
        assert _participant_user_ids({}) is None

    warnings = [r for r in caplog.records if "malformed participant_user_ids" in r.getMessage()]
    assert len(warnings) == 1
    assert "subj.x" in warnings[0].getMessage()
    assert "corr-1" in warnings[0].getMessage()
