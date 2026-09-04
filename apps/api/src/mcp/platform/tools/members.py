from __future__ import annotations

from src.core.permissions import MEMBER_READ
from src.mcp.platform.registry import platform_tool


@platform_tool("member.list", MEMBER_READ, description="List workspace members with roles.")
async def member_list(*, workspace_id: str, **_: object) -> list[dict]:
    from src.db.session import SessionFactory
    from src.services.workspaces import WorkspaceService

    async with SessionFactory() as session:
        svc = WorkspaceService(session)
        rows = await svc.list_members(workspace_id)
        return [
            {"user_id": m.user_id, "email": u.email, "role": r.name, "permissions": r.permissions}
            for (m, u, r) in rows
        ]
