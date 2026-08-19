from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect

from src.api.deps import websocket_auth

logger = logging.getLogger(__name__)

router = APIRouter(tags=["realtime"])


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user=Depends(websocket_auth)):
    manager = websocket.app.state.container.connection_manager
    await manager.connect(user.id, websocket)
    try:
        await websocket.send_json({"event": "connected", "data": {"user_id": user.id}})
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(user.id, websocket)
