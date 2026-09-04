from __future__ import annotations

from src.core.permissions import MESSAGE_READ
from src.mcp.platform.registry import platform_tool


@platform_tool("conversation.list", MESSAGE_READ, description="List conversations in this workspace.")
async def conversation_list(*, workspace_id: str, triggering_user_id: str | None = None, **_: object) -> list[dict]:
    from src.db.session import SessionFactory
    from src.services.conversations import ConversationService

    uid = triggering_user_id or ""
    if not uid:
        return []
    async with SessionFactory() as session:
        svc = ConversationService(session)
        rows, _ = await svc.list_conversations(workspace_id=workspace_id, user_id=uid, limit=20)
        return [{"id": r["id"], "title": r.get("title"), "last_message_preview": r.get("last_message_preview")} for r in rows]


@platform_tool("conversation.rename", MESSAGE_READ, mutates=True, description="Rename a conversation.")
async def conversation_rename(*, workspace_id: str, conversation_id: str, title: str, agent_id: str | None = None, **_: object) -> dict:
    from src.db.session import SessionFactory
    from src.services.conversations import ConversationService

    async with SessionFactory() as session:
        svc = ConversationService(session)
        data = await svc.rename(
            workspace_id=workspace_id,
            conversation_id=conversation_id,
            title=title,
            actor_agent_id=agent_id,
            actor_type="agent" if agent_id else "user",
        )
        return {"id": data["id"], "title": data.get("title")}
