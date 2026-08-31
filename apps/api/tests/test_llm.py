import pytest

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