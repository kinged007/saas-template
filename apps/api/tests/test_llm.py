import pytest
from types import SimpleNamespace

from src.agents import llm


class FakeResp:
    def __init__(self, *, status=200, body=b"", lines=None):
        self.status_code = status
        self._body = body
        self._lines = lines or []

    async def aread(self):
        return self._body

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class FakeClient:
    """httpx.AsyncClient double capturing the request, returning canned SSE."""

    def __init__(self, *, status=200, body=b"", lines=None):
        self.status, self.body, self.lines = status, body, lines or []
        self.calls: list[tuple[str, str, dict, dict]] = []
        self.closed = False

    def stream(self, method, url, json=None, headers=None):
        self.calls.append((method, url, json or {}, headers or {}))

        class CM:
            async def __aenter__(inner):
                return FakeResp(status=self.status, body=self.body, lines=self.lines)

            async def __aexit__(inner, *exc):
                return False

        return CM()

    async def aclose(self):
        self.closed = True


@pytest.mark.anyio
async def test_stream_chat_yields_tokens_and_done():
    fake = FakeClient(
        lines=[
            'data: {"choices":[{"delta":{"content":"Hel"}}]}',
            'data: {"choices":[{"delta":{"content":"lo"}}]}',
            'data: {"choices":[{"delta":{"content":"!"}}]}',
            "data: [DONE]",
        ]
    )
    events = [
        e
        async for e in llm.stream_chat(
            model="gpt-4o-mini",
            env={"OPENAI_API_KEY": "sk-test"},
            system_prompt="You are helpful.",
            history=[{"sender_type": "user", "body": "hi"}],
            http=fake,
        )
    ]
    assert [e["type"] for e in events] == ["token", "token", "token", "done"]
    text = "".join(e["data"]["text"] for e in events if e["type"] == "token")
    assert text == "Hello!"

    method, url, payload, headers = fake.calls[0]
    assert method == "POST"
    assert url.endswith("/chat/completions")
    assert headers["Authorization"] == "Bearer sk-test"
    assert payload["messages"][0] == {"role": "system", "content": "You are helpful."}
    assert payload["messages"][1] == {"role": "user", "content": "hi"}
    assert payload["stream"] is True
    # injected clients are caller-owned — the module must not close them
    assert fake.closed is False


@pytest.mark.anyio
async def test_stream_chat_no_key_reports_configuration_error():
    events = [
        e
        async for e in llm.stream_chat(
            model="gpt-4o-mini",
            env={},
            system_prompt=None,
            history=[],
            http=FakeClient(),
        )
    ]
    assert events[0]["type"] == "error"
    assert "API key" in events[0]["data"]["message"]


@pytest.mark.anyio
async def test_stream_chat_http_error_status():
    fake = FakeClient(status=401, body=b'{"error":"invalid api key"}')
    events = [
        e
        async for e in llm.stream_chat(
            model="m", env={"OPENAI_API_KEY": "k"}, system_prompt=None, history=[], http=fake
        )
    ]
    assert events[0]["type"] == "error"
    assert "401" in events[0]["data"]["message"]
    assert "invalid api key" in events[0]["data"]["message"]


@pytest.mark.anyio
async def test_stream_chat_overrides_base_url():
    fake = FakeClient(lines=["data: [DONE]"])
    events = [
        e
        async for e in llm.stream_chat(
            model="llama3",
            env={"OPENAI_API_KEY": "k", "OPENAI_BASE_URL": "http://localhost:11434/v1"},
            system_prompt=None,
            history=[],
            http=fake,
        )
    ]
    assert events[-1]["type"] == "done"
    assert fake.calls[0][1] == "http://localhost:11434/v1/chat/completions"


@pytest.mark.anyio
async def test_stream_chat_openrouter_uses_own_key_and_base_url():
    fake = FakeClient(lines=["data: [DONE]"])
    events = [
        e
        async for e in llm.stream_chat(
            model="openrouter/free",
            env={"OPENROUTER_API_KEY": "sk-or"},
            system_prompt=None,
            history=[],
            http=fake,
        )
    ]
    assert events[-1]["type"] == "done"
    method, url, payload, headers = fake.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-or"
    assert payload["model"] == "openrouter/free"


@pytest.mark.anyio
async def test_openai_base_url_never_redirects_openrouter_family():
    """OPENAI_BASE_URL (even pointing at openai.com) must not apply to the
    OpenRouter family — an OpenRouter key must never hit api.openai.com."""
    fake = FakeClient(status=401, body=b'{"error":"unauthorized"}')
    async for _ in llm.stream_chat(
        model="openrouter/free",
        env={"OPENROUTER_API_KEY": "sk-or", "OPENAI_BASE_URL": "https://api.openai.com/v1"},
        system_prompt=None,
        history=[],
        http=fake,
    ):
        pass
    assert fake.calls[0][1] == "https://openrouter.ai/api/v1/chat/completions"


@pytest.mark.anyio
async def test_unrecognized_model_defaults_to_openrouter():
    fake = FakeClient(lines=["data: [DONE]"])
    events = [
        e
        async for e in llm.stream_chat(
            model="some/vendor-model",
            env={"OPENROUTER_API_KEY": "sk-or"},
            system_prompt=None,
            history=[],
            http=fake,
        )
    ]
    assert events[-1]["type"] == "done"
    method, url, payload, headers = fake.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-or"


class FakeJsonClient:
    """httpx.AsyncClient double for non-streaming completions (memory extraction)."""

    def __init__(self, *, status=200, body=None):
        self.status = status
        self.body = body if body is not None else {"choices": [{"message": {"content": "[]"}}]}
        self.calls: list[tuple[str, dict, dict]] = []
        self.closed = False

    async def post(self, url, json=None, headers=None):
        self.calls.append((url, json or {}, headers or {}))
        status, body = self.status, self.body
        return SimpleNamespace(status_code=status, json=lambda: body)

    async def aclose(self):
        self.closed = True


@pytest.mark.anyio
async def test_extract_memories_parses_json():
    fake = FakeJsonClient(
        body={"choices": [{"message": {"content": '[{"kind": "fact", "content": "likes X"}]'}}]}
    )
    items = await llm.extract_memories(
        model="m", env={"OPENAI_API_KEY": "k"}, transcript="user: hi", http=fake
    )
    assert items == [{"kind": "fact", "content": "likes X"}]
    url, payload, headers = fake.calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer k"
    assert payload["stream"] is False
    assert "user: hi" in payload["messages"][0]["content"]
    assert fake.closed is False


@pytest.mark.anyio
async def test_extract_memories_handles_fenced_json_and_junk():
    ok_env = {"OPENAI_API_KEY": "k"}
    fenced = FakeJsonClient(
        body={
            "choices": [
                {
                    "message": {
                        "content": '```json\n[{"kind":"summary","content":"covered"}]\n```'
                    }
                }
            ]
        }
    )
    items = await llm.extract_memories(
        model="m", env={"LLM_API_KEY": "k"}, transcript="t", http=fenced
    )
    assert items == [{"kind": "summary", "content": "covered"}]

    # malformed kinds / missing content are dropped, valid ones kept
    mixed = FakeJsonClient(
        body={
            "choices": [
                {
                    "message": {
                        "content": (
                            '[{"kind": "rumor", "content": "x"}, '
                            '{"kind": "preference", "content": ""}, '
                            '{"kind": "fact", "content": "ok"}]'
                        )
                    }
                }
            ]
        }
    )
    items = await llm.extract_memories(model="m", env=ok_env, transcript="t", http=mixed)
    assert items == [{"kind": "fact", "content": "ok"}]

    # non-JSON prose with a JSON array buried in it
    prose = FakeJsonClient(
        body={
            "choices": [
                {
                    "message": {
                        "content": (
                            'Here you go:\n[{"kind": "fact", "content": "buried"}] Hope that helps.'
                        )
                    }
                }
            ]
        }
    )
    items = await llm.extract_memories(model="m", env=ok_env, transcript="t", http=prose)
    assert items == [{"kind": "fact", "content": "buried"}]

    garbage = FakeJsonClient(body={"choices": [{"message": {"content": "not json at all"}}]})
    assert await llm.extract_memories(model="m", env=ok_env, transcript="t", http=garbage) == []


@pytest.mark.anyio
async def test_extract_memories_skips_without_key_and_on_http_error():
    # no API key configured → skipped silently, no request
    no_key = FakeJsonClient()
    assert await llm.extract_memories(model="m", env={}, transcript="t", http=no_key) == []
    assert no_key.calls == []

    # non-200 → []
    err = FakeJsonClient(status=500, body={"error": "boom"})
    assert (
        await llm.extract_memories(model="m", env={"OPENAI_API_KEY": "k"}, transcript="t", http=err)
        == []
    )