from __future__ import annotations

import json
from pathlib import Path

from src.settings import settings


class SessionStore:
    """Filesystem JSON session history per (workspace, agent, conversation, session_id).

    Storage layout (under agent_runner_root):
      {root}/{workspace_id}/{agent_id}/{conversation_id}/{session_id}.json
    """

    def __init__(self, root: str | None = None) -> None:
        self.root = Path(root or settings.agent_runner_root)

    def _path(self, workspace_id: str, agent_id: str, conversation_id: str, session_id: str) -> Path:
        safe_session = session_id.replace("/", "_").replace("\\", "_")
        return self.root / workspace_id / agent_id / conversation_id / f"{safe_session}.json"

    async def write(self, workspace_id: str, agent_id: str, conversation_id: str, session_id: str, history: list[dict]) -> None:
        p = self._path(workspace_id, agent_id, conversation_id, session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        # use sync I/O; Phase 4 only, small JSON
        p.write_text(json.dumps(history, ensure_ascii=False), encoding="utf-8")

    async def read(self, workspace_id: str, agent_id: str, conversation_id: str, session_id: str) -> list[dict] | None:
        p = self._path(workspace_id, agent_id, conversation_id, session_id)
        if not p.exists():
            return None
        return json.loads(p.read_text(encoding="utf-8"))

    async def delete(self, workspace_id: str, agent_id: str, conversation_id: str, session_id: str) -> None:
        p = self._path(workspace_id, agent_id, conversation_id, session_id)
        try:
            p.unlink(missing_ok=True)
        except Exception:
            pass
