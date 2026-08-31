"""Minimal OpenAI-compatible streaming chat client (no vendor SDK).

Speaks the `/chat/completions` SSE protocol with httpx, so it works against
OpenAI, OpenRouter, Ollama, vLLM, LiteLLM — any OpenAI-compatible endpoint
(`OPENAI_BASE_URL` override). API keys come from per-agent secrets
(`agent:{agent_id}:*`, resolved in `ChatHandler.collect_context`) or the
server process env; values are never logged.

Pydantic AI (the plan's Phase-8 harness) is not needed yet — chat-only
invocation has no tools/MCP loop, and the handler interface lets us swap the
harness later without touching the pipeline.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Key to try per model family; agent secrets win over process env.
_KEY_ORDER: dict[str, list[str]] = {
    "openrouter": ["OPENROUTER_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "local": ["OPENAI_API_KEY", "LLM_API_KEY", "ANTHROPIC_API_KEY"],
}

# Base URL per model family (env OPENAI_BASE_URL still overrides).
_DEFAULT_BASE_URLS: dict[str, str] = {
    "openrouter": "https://openrouter.ai/api/v1",
}


def _family(model: str) -> str:
    m = (model or "").lower()
    for name in _KEY_ORDER:
        if name in m:
            return name
    return "local"


def _select_key(model: str, env: dict[str, str]) -> str | None:
    family = _family(model)
    for key in _KEY_ORDER[family]:
        value = env.get(key) or os.environ.get(key)
        if value:
            return value
    return None


def _to_messages(system_prompt: str | None, history: list[dict]) -> list[dict]:
    """System prompt + conversation history mapped to chat roles."""
    messages: list[dict] = []
    if system_prompt and system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt.strip()})
    for h in history[-20:]:
        role = "assistant" if h.get("sender_type") == "agent" else "user"
        body = (h.get("body") or "").strip()
        if body:
            messages.append({"role": role, "content": body})
    return messages


async def stream_chat(
    *,
    model: str | None,
    env: dict[str, str],
    system_prompt: str | None,
    history: list[dict],
    temperature: float | None = None,
    max_tokens: int | None = None,
    http: Any = None,  # injectable for tests
) -> AsyncIterator[dict]:
    """Yield event dicts: {"type":"token"|"error"|"done", "data": {...}}."""
    model = (model or "").strip() or DEFAULT_MODEL
    family = _family(model)
    api_key = _select_key(model, env)
    if not api_key:
        yield {
            "type": "error",
            "data": {
                "message": (
                    "No LLM API key configured for this agent. Set the agent secret "
                    "OPENROUTER_API_KEY, OPENAI_API_KEY or ANTHROPIC_API_KEY (matching "
                    "the model's provider) in Agents → edit → Secrets & env, or set the "
                    "corresponding variable in the server environment."
                ),
            },
        }
        return
    base_url = (
        env.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_BASE_URL")
        or _DEFAULT_BASE_URLS.get(family, DEFAULT_BASE_URL)
    ).rstrip("/")
    payload: dict[str, Any] = {
        "model": model,
        "messages": _to_messages(system_prompt, history),
        "stream": True,
    }
    if temperature is not None:
        payload["temperature"] = temperature
    if max_tokens is not None:
        payload["max_tokens"] = max_tokens

    client = http or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        async with client.stream(
            "POST",
            f"{base_url}/chat/completions",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        ) as resp:
            if resp.status_code != 200:
                detail = (await resp.aread()).decode(errors="replace")[:300]
                yield {
                    "type": "error",
                    "data": {"message": f"LLM error {resp.status_code}: {detail}"},
                }
                return
            async for line in resp.aiter_lines():
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    chunk = json.loads(data)
                except json.JSONDecodeError:
                    continue  # keepalive/empty frames
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                text = delta.get("content") or ""
                if text:
                    yield {"type": "token", "data": {"text": text}}
    except Exception as exc:  # noqa: BLE001 — surface any transport failure
        logger.warning("LLM stream failed for model %s: %s", model, exc)
        yield {"type": "error", "data": {"message": f"LLM request failed: {exc}"}}
    finally:
        if http is None:
            await client.aclose()
    yield {"type": "done", "data": {}}