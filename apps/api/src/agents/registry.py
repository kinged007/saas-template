from __future__ import annotations

from src.agents.handlers.base import AgentHandler

handler_registry: dict[str, AgentHandler] = {}


def register_handler(handler: AgentHandler) -> None:
    handler_registry[handler.entity_type] = handler


def get_handler(entity_type: str) -> AgentHandler | None:
    return handler_registry.get(entity_type)
