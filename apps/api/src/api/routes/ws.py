from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.api.deps import authenticate_websocket_token
from src.db.session import SessionFactory

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])

AUTH_TIMEOUT_SECONDS = 10.0
CLOSE_POLICY_VIOLATION = 4401


async def _authenticate(websocket: WebSocket):
    """Complete the auth handshake: the first frame must carry the token.

    The access token travels as a message instead of a query parameter so it
    never lands in proxy or access logs. The DB session is created and closed
    here — never held for the socket's lifetime. On failure the socket is
    closed with a policy-violation code and None is returned.
    """
    await websocket.accept()
    try:
        raw = await asyncio.wait_for(websocket.receive_text(), timeout=AUTH_TIMEOUT_SECONDS)
    except (TimeoutError, WebSocketDisconnect):
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="auth timeout")
        return None
    try:
        frame = json.loads(raw)
    except ValueError:
        frame = {}
    token = frame.get("token") if frame.get("type") == "auth" else None
    async with SessionFactory() as db:
        user = await authenticate_websocket_token(db, token)
    if user is None:
        await websocket.close(code=CLOSE_POLICY_VIOLATION, reason="invalid token")
        return None
    return user


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Realtime gateway.

    Handshake: client sends `{"type": "auth", "token": "..."}` as its first
    frame; the server replies `{"event": "connected", ...}` and then pushes
    realtime events. While open, the client pings every ~25s and the server
    answers `{"event": "pong"}` — regular traffic in both directions keeps
    idle connections from being dropped by intermediaries (e.g. nginx's
    default 60s proxy read timeout).
    """
    manager = websocket.app.state.container.connection_manager
    user = await _authenticate(websocket)
    if user is None:
        return
    await manager.connect(user.id, websocket)
    await websocket.send_json({"event": "connected", "data": {"user_id": user.id}})
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                frame = json.loads(raw)
            except ValueError:
                continue
            if frame.get("type") == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user.id, websocket)
