from __future__ import annotations

from src.core.permissions import WORKSPACE_READ, WORKSPACE_UPDATE
from src.mcp.platform.registry import platform_tool


@platform_tool("workspace.read", WORKSPACE_READ, description="Read the current workspace by id.")
async def workspace_read(*, workspace_id: str, **_: object) -> dict:
    from src.db.session import SessionFactory
    from src.models.workspace import Workspace

    async with SessionFactory() as session:
        ws = await session.get(Workspace, workspace_id)
        if ws is None:
            return {"error": "workspace not found"}
        return {"id": ws.id, "name": ws.name, "slug": ws.slug, "description": ws.description}


@platform_tool("workspace.update", WORKSPACE_UPDATE, mutates=True, description="Update workspace name/description.")
async def workspace_update(*, workspace_id: str, name: str | None = None, description: str | None = None, **_: object) -> dict:
    from src.db.session import SessionFactory
    from src.services.workspaces import WorkspaceService

    async with SessionFactory() as session:
        svc = WorkspaceService(session)
        ws = await svc.update_workspace(workspace_id, name=name, description=description)
        return {"id": ws.id, "name": ws.name, "slug": ws.slug}
