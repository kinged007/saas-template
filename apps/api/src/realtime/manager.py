"""WebSocket session manager: per-user connections with realtime push.

Every connected frontend registers (user_id, websocket). Realtime events
published by workflows (in-process or via NATS subscribers) call `push`,
which fans out to all sessions of the target user.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._sessions: dict[str, set[WebSocket]] = defaultdict(set)
        self._lock = asyncio.Lock()

    async def connect(self, user_id: str, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._sessions[user_id].add(ws)
        logger.debug("ws connected: user=%s", user_id)

    async def disconnect(self, user_id: str, ws: WebSocket) -> None:
        async with self._lock:
            sessions = self._sessions.get(user_id)
            if sessions:
                sessions.discard(ws)
                if not sessions:
                    self._sessions.pop(user_id, None)

    def active_sessions(self) -> int:
        return sum(len(v) for v in self._sessions.values())

    async def push(
        self,
        user_id: str,
        payload: dict,
        *,
        notification: dict | None = None,
        event: str | None = None,
    ) -> None:
        """Send an event to every live session of `user_id`."""
        message = {
            "event": event or "notification.created",
            "data": notification if notification is not None else payload,
        }
        sessions = list(self._sessions.get(user_id, ()))
        for ws in sessions:
            try:
                await ws.send_json(message)
            except Exception:
                logger.warning("ws send failed, dropping session", exc_info=True)
                await self.disconnect(user_id, ws)
