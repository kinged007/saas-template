"""Triple-isolated memory store for agents.

A memory always belongs to exactly one (workspace_id, agent_profile_id,
user_id) triple: every query and write filters on all three ids, so no code
path can read across agents, users, or workspaces. Same shape as
``agents/sessions/store.py`` — a small async class handlers construct on
demand; SQLAlchemy-backed (unlike SessionStore) because memories must survive
restarts and be queryable by similarity/recency.

Embeddings: the ``embedding`` column is only populated when
``settings.vector_enabled`` AND a caller supplies an embedding function
(there is no built-in provider yet); otherwise retrieval is recency-only,
which is the whole dev story.
"""

from __future__ import annotations

import math
from collections.abc import Callable

from sqlalchemy import delete, select, update

from src.db.session import SessionFactory
from src.models.memory import AgentMemory
from src.settings import settings

MEMORY_KINDS = frozenset({"fact", "preference", "summary"})


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity, None-safe for the nullable embedding column."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _row_dict(row: AgentMemory, score: float | None = None) -> dict:
    return {
        "kind": row.kind,
        "content": row.content,
        "conversation_id": row.conversation_id,
        "score": score,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


class MemoryStore:
    """Stores and retrieves memories scoped to one (workspace, agent, user) triple."""

    def __init__(self, session_factory=None) -> None:
        self._session_factory = session_factory or SessionFactory

    # ---------------------------------------------------------------- writes

    async def upsert_many(
        self,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        conversation_id: str | None,
        items: list[dict],
    ) -> int:
        """Upsert extracted memories: re-inserting identical content refreshes
        it (so it resurfaces in recency order) instead of duplicating it."""
        added = 0
        async with self._session_factory() as session:
            for item in items:
                kind = item.get("kind")
                content = (item.get("content") or "").strip()
                if kind not in MEMORY_KINDS or not content:
                    continue  # barricade: never store unvalidated kinds
                existing = await session.execute(
                    select(AgentMemory.id).where(
                        AgentMemory.workspace_id == workspace_id,
                        AgentMemory.agent_profile_id == agent_id,
                        AgentMemory.user_id == user_id,
                        AgentMemory.kind == kind,
                        AgentMemory.content == content,
                    )
                )
                row_id = existing.scalar_one_or_none()
                if row_id is not None:
                    await session.execute(
                        update(AgentMemory)
                        .where(AgentMemory.id == row_id)
                        .values(conversation_id=conversation_id)
                    )
                    continue
                session.add(
                    AgentMemory(
                        workspace_id=workspace_id,
                        agent_profile_id=agent_id,
                        user_id=user_id,
                        conversation_id=conversation_id,
                        kind=kind,
                        content=content,
                    )
                )
                added += 1
            await session.commit()
        return added

    async def prune(
        self,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        keep: int | None = None,
    ) -> int:
        """Cap stored memories per kind per triple, newest first. Returns the
        number of deleted memories."""
        keep = keep or settings.agent_memory_prune_keep
        res = await self._query_rows(workspace_id, agent_id, user_id, order_recent=True)
        excess: list[str] = []
        counts: dict[str, int] = {}
        for row in res:
            counts[row.kind] = counts.get(row.kind, 0) + 1
            if counts[row.kind] > keep:
                excess.append(row.id)
        if not excess:
            return 0
        async with self._session_factory() as session:
            await session.execute(delete(AgentMemory).where(AgentMemory.id.in_(excess)))
            await session.commit()
        return len(excess)

    # ------------------------------------------------------------- retrieval

    async def retrieve(
        self,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        *,
        limit: int = 10,
        kinds: list[str] | None = None,
        query: str | None = None,
        embed: Callable[[str], list[float]] | None = None,
    ) -> list[dict]:
        """Top-k memories for the triple.

        With ``settings.vector_enabled`` and an ``embed`` callable, ranks by
        embedding similarity to ``query``; otherwise recency-only (updated_at
        desc), which is the dev fallback. Triples are never mixed.
        """
        rows = await self._query_rows(
            workspace_id,
            agent_id,
            user_id,
            kinds=kinds,
            order_recent=not (settings.vector_enabled and embed),
        )
        if settings.vector_enabled and embed and query:
            query_embedding = embed(query)
            ranked = sorted(
                ((_cosine_similarity(row.embedding or [], query_embedding), row) for row in rows),
                key=lambda pair: pair[0],
                reverse=True,
            )
            return [_row_dict(row, score=score) for score, row in ranked[:limit]]
        return [_row_dict(row) for row in rows[:limit]]

    # ---------------------------------------------------------------- internals

    async def _query_rows(
        self,
        workspace_id: str,
        agent_id: str,
        user_id: str,
        *,
        kinds: list[str] | None = None,
        order_recent: bool = True,
    ) -> list[AgentMemory]:
        stmt = select(AgentMemory).where(
            AgentMemory.workspace_id == workspace_id,
            AgentMemory.agent_profile_id == agent_id,
            AgentMemory.user_id == user_id,
        )
        if kinds:
            stmt = stmt.where(AgentMemory.kind.in_(kinds))
        if order_recent:
            stmt = stmt.order_by(AgentMemory.updated_at.desc())
        async with self._session_factory() as session:
            res = await session.execute(stmt)
            return list(res.scalars().all())