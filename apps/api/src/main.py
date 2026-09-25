from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.api.routes import (
    admin,
    api_keys,
    audit,
    auth,
    conversations,
    invitations,
    jobs,
    members,
    meta,
    notifications,
    oauth,
    profiles,
    roles,
    webhooks,
    workspaces,
    ws,
)
from src.container import Container
from src.core.request_id import RequestIdMiddleware
from src.db.session import SessionFactory
from src.events.factory import WorkflowRegistry
from src.jobs.capture import install_run_capture, uninstall_run_capture
from src.jobs.scheduler import JobScheduler
from src.services.jobs import JobService
from src.services.webhook_dispatcher import WebhookDispatcher
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
    build_workflows(registry, container.bus, container.connection_manager, container.cipher)
    await registry.wire()
    await registry.start()

    # Provision job definitions from the in-code registry (idempotent), then
    # start the due-job scheduler loop. Log capture must be installed before
    # any run can execute.
    async with SessionFactory() as session:
        # Keep system roles converged on the code defaults (e.g. new audit:read
        # permission for admin/owner). Idempotent and cheap.
        from src.services.workspaces import WorkspaceService

        try:
            await WorkspaceService(session).sync_system_role_permissions()
        except Exception:
            logger.exception("failed to sync system role permissions")
        await JobService(session, container.bus, container.cipher).sync_definitions()
    install_run_capture()
    scheduler = JobScheduler(bus=container.bus)
    app.state.job_scheduler = scheduler
    await scheduler.start()
    dispatcher = WebhookDispatcher(secret_store=container.secret_store)
    app.state.webhook_dispatcher = dispatcher
    await dispatcher.start()
    logger.info(
        "event bus (%s) started; workflows: %s",
        container.bus.name,
        ", ".join(registry.subjects),
    )
    try:
        yield
    finally:
        await dispatcher.stop()
        await scheduler.stop()
        uninstall_run_capture()
        await registry.stop()


app = FastAPI(
    title=settings.api_name,
    version="0.1.0",
    description=f"Backend API for {settings.app_name}",
    lifespan=lifespan,
)

app.add_middleware(RequestIdMiddleware)
API_VERSION = "v1"
API_VERSION_HEADER = "X-API-Version"


class ApiVersionMiddleware(BaseHTTPMiddleware):
    """Stamp every /api/* response with the API version (see docs/API_VERSIONING.md)."""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers[API_VERSION_HEADER] = API_VERSION
        return response


app.add_middleware(ApiVersionMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=[
        "X-Total-Count",
        "X-API-Version",
        "X-API-Key-Quota",
        "X-API-Key-Remaining",
        "X-Request-ID",
    ],
)

app.state.container = Container()


@app.get("/")
async def root() -> dict:
    return {
        "service": settings.service_name,
        "api_version": API_VERSION,
        "docs": "/docs",
        "health": "/healthz",
    }


API = "/api/v1"
app.include_router(meta.router, prefix=API)
app.include_router(admin.router, prefix=API)
app.include_router(auth.router, prefix=API)
app.include_router(oauth.router, prefix=API)
app.include_router(workspaces.router, prefix=API)
app.include_router(members.router, prefix=API)
app.include_router(invitations.router, prefix=API)
app.include_router(roles.router, prefix=API)
app.include_router(api_keys.router, prefix=API)
app.include_router(jobs.router, prefix=API)
app.include_router(webhooks.router, prefix=API)
app.include_router(notifications.router, prefix=API)
app.include_router(conversations.router, prefix=API)
app.include_router(profiles.router, prefix=API)
app.include_router(audit.router, prefix=API)
app.include_router(ws.router, prefix=API)
