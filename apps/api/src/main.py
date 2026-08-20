from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import (
    api_keys,
    auth,
    invitations,
    members,
    meta,
    notifications,
    roles,
    workspaces,
    ws,
)
from src.container import Container
from src.events.factory import WorkflowRegistry
from src.settings import settings
from src.workflows import build_workflows

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    container: Container = app.state.container
    registry = WorkflowRegistry(container.bus)
    build_workflows(registry, container.bus, container.connection_manager)
    await registry.wire()
    await registry.start()
    logger.info(
        "event bus (%s) started; workflows: %s",
        container.bus.name,
        ", ".join(registry.subjects),
    )
    try:
        yield
    finally:
        await registry.stop()


app = FastAPI(
    title="SaaS Template API",
    version="0.1.0",
    description="General-purpose SaaS template",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Total-Count"],
)

app.state.container = Container()


@app.get("/")
async def root() -> dict:
    return {"service": "saas-template-api", "docs": "/docs", "health": "/healthz"}


API = "/api/v1"
app.include_router(meta.router, prefix=API)
app.include_router(auth.router, prefix=API)
app.include_router(workspaces.router, prefix=API)
app.include_router(members.router, prefix=API)
app.include_router(invitations.router, prefix=API)
app.include_router(roles.router, prefix=API)
app.include_router(api_keys.router, prefix=API)
app.include_router(notifications.router, prefix=API)
app.include_router(ws.router, prefix=API)
