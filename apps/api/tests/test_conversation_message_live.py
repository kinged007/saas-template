"""Tests: the live fanout consumer pushes the thread update once per unique participant.

A repeated id in `participant_user_ids` must deliver `message.created` once, not
once per occurrence, preserving first-seen order — same rule as the durable path
(`on_conversation_message`).
"""

from __future__ import annotations

from src.events.bus import EventMetadata
from src.events.factory import WorkflowRegistry
from src.events.subjects import Subjects
from src.workflows import build_workflows


class _RecordingConnectionManager:
    def __init__(self) -> None:
        self.calls: list[tuple[list[str], str | None]] = []

    async def push_many(self, user_ids, payload, event=None):
        self.calls.append((list(user_ids), event))


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
    cm = _RecordingConnectionManager()
    registry = WorkflowRegistry(bus)
    build_workflows(registry, bus, cm)
    handler = registry._entries[Subjects.CONVERSATION_MESSAGE_LIVE][0]
    return handler, cm


async def test_live_message_pushes_each_participant_once_in_first_seen_order():
    handler, cm = _wired()
    await handler(
        {
            "workspace_id": "w1",
            "conversation_id": "c1",
            "participant_user_ids": ["u2", "u1", "u2", "u1", "u3"],
        },
        EventMetadata(subject=Subjects.CONVERSATION_MESSAGE_LIVE),
    )

    assert cm.calls == [(["u2", "u1", "u3"], "message.created")]


async def test_live_message_no_participants_pushes_nothing():
    handler, cm = _wired()
    for payload in ({}, {"participant_user_ids": []}, {"participant_user_ids": None}):
        await handler(payload, EventMetadata(subject=Subjects.CONVERSATION_MESSAGE_LIVE))

    assert cm.calls == []
