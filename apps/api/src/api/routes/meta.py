from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import PlainTextResponse

from src.core.metrics import render_prometheus

logger = logging.getLogger(__name__)

router = APIRouter(tags=["meta"])


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok", "service": "saas-template-api"}


@router.get("/metrics")
async def metrics() -> PlainTextResponse:
    return PlainTextResponse(render_prometheus(), media_type="text/plain; version=0.0.4")


@router.get("/readyz")
async def readyz(request: Request) -> dict:
    return {
        "status": "ok",
        "event_bus": request.app.state.container.bus.name,
        "ws_sessions": request.app.state.container.connection_manager.active_sessions(),
    }
