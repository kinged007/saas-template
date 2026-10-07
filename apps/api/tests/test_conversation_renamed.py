"""Tests: the conversation.renamed fanout consumer pushes the rename once per unique participant.

A repeated id in `participant_user_ids` must deliver `conversation.renamed`
once, not once per occurrence, preserving first-seen order — same rule as the
`message.created` consumers (`on_conversation_message`,
`on_conversation_message_live`).
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
    handler = registry._entries[Subjects.CONVERSATION_RENAMED][0]
    return handler, cm


async def test_renamed_pushes_each_participant_once_in_first_seen_order():
    handler, cm = _wired()
    await handler(
        {
            "workspace_id": "w1",
            "conversation_id": "c1",
            "participant_user_ids": ["u2", "u1", "u2", "u1", "u3"],
        },
        EventMetadata(subject=Subjects.CONVERSATION_RENAMED),
    )

    assert cm.calls == [(["u2", "u1", "u3"], "conversation.renamed")]


async def test_renamed_no_participants_pushes_nothing():
    handler, cm = _wired()
    for payload in ({}, {"participant_user_ids": []}, {"participant_user_ids": None}):
        await handler(payload, EventMetadata(subject=Subjects.CONVERSATION_RENAMED))

    assert cm.calls == []
