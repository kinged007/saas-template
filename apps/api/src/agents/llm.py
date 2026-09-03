"""Minimal OpenAI-compatible streaming chat client (no vendor SDK).

Speaks the `/chat/completions` SSE protocol with httpx, so it works against
OpenAI, OpenRouter, Ollama, vLLM, LiteLLM — any OpenAI-compatible endpoint.
OpenRouter is the default provider: unrecognized model ids and the fallback
`DEFAULT_MODEL` all route to OpenRouter. API keys come from per-agent secrets
(`agent:{agent_id}:*`, resolved in `ChatHandler.collect_context`) or the
server process env; values are never logged. Endpoints are overridable per
family via `OPENROUTER_BASE_URL` / `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`.

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

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"  # default provider
DEFAULT_MODEL = "openrouter/free"  # OpenRouter's free-model router id
_TIMEOUT = httpx.Timeout(120.0, connect=10.0)

# Key to try per model family; agent secrets win over process env.
_KEY_ORDER: dict[str, list[str]] = {
    "openrouter": ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "LLM_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY", "OPENAI_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "local": ["OPENAI_API_KEY", "LLM_API_KEY", "ANTHROPIC_API_KEY"],
}

# Family-specific endpoint; each family is overridable only via its own
# *_BASE_URL var (OPENAI_BASE_URL must not redirect the OpenRouter family).
_BASE_URL_ENV: dict[str, str] = {
    "openrouter": "OPENROUTER_BASE_URL",
    "anthropic": "ANTHROPIC_BASE_URL",
    "openai": "OPENAI_BASE_URL",
    "local": "OPENAI_BASE_URL",
}
_DEFAULT_BASE_URLS: dict[str, str] = {
    "openrouter": DEFAULT_BASE_URL,
    "anthropic": "https://api.anthropic.com/v1",
    "openai": "https://api.openai.com/v1",
}


def _family(model: str, env: dict[str, str]) -> str:
    m = (model or "").lower()
    for name in ("openrouter", "anthropic", "openai"):
        if name in m:
            return name
    # No recognizable provider: an explicit self-hosted endpoint (OPENAI_BASE_URL)
    # means local; otherwise the default provider (OpenRouter) handles it.
    return "local" if env.get("OPENAI_BASE_URL") or os.environ.get("OPENAI_BASE_URL") else "openrouter"


def _select_key(model: str, env: dict[str, str]) -> str | None:
    family = _family(model, env)
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
    family = _family(model, env)
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
    base_env = _BASE_URL_ENV.get(family, "OPENAI_BASE_URL")
    base_url = (
        env.get(base_env)
        or os.environ.get(base_env)
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


async def extract_memories(
    *,
    model: str | None,
    env: dict[str, str],
    transcript: str,
    http: Any = None,  # injectable for tests
) -> list[dict]:
    """Distill a conversation turn into durable memories via a one-shot LLM call.

    Returns a list of ``{"kind": "fact"|"preference"|"summary", "content": str}``.
    Never raises: extraction is best-effort, any failure yields [] so memory
    problems can never break the chat turn itself. With no API key configured
    the call is skipped entirely (same key resolution as stream_chat).
    """
    model = (model or "").strip() or DEFAULT_MODEL
    api_key = _select_key(model, env)
    if not api_key:
        return []
    base_env = _BASE_URL_ENV.get(_family(model, env), "OPENAI_BASE_URL")
    base_url = (
        env.get(base_env)
        or os.environ.get(base_env)
        or _DEFAULT_BASE_URLS.get(_family(model, env), DEFAULT_BASE_URL)
    ).rstrip("/")
    prompt = (
        "You distill conversation turns into durable agent memory. From the turn below, "
        'extract facts (stable facts about the user or their work), preferences (how the '
        'user wants things done), and summaries (short recap of what was decided or covered). '
        'Return ONLY a JSON array of objects: [{"kind": "fact"|"preference"|"summary", '
        '"content": "<one short plain-text statement>"}]. Return [] if nothing durable.\n\n'
        f"{transcript}"
    )
    payload: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False,
        "max_tokens": 500,
    }
    client = http or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        resp = await client.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        )
        if resp.status_code != 200:
            logger.warning("memory extraction failed with HTTP %s", resp.status_code)
            return []
        data = resp.json()
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        return _parse_memories(content)
    except Exception as exc:  # noqa: BLE001 — extraction must never break the turn
        logger.warning("memory extraction failed for model %s: %s", model, exc)
        return []
    finally:
        if http is None:
            await client.aclose()


def _parse_memories(content: str) -> list[dict]:
    """Parse the LLM's JSON answer defensively: strip fences, tolerate junk."""
    text = content.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # LLMs sometimes wrap the array in prose; take the first [...] block
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            return []
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return []
    if not isinstance(data, list):
        return []
    valid: list[dict] = []
    for item in data[:20]:
        if not isinstance(item, dict):
            continue
        kind = item.get("kind")
        content = (item.get("content") or "").strip()
        if kind in ("fact", "preference", "summary") and content:
            valid.append({"kind": kind, "content": content})
    return valid