import httpx
import pytest
import respx

from app.llm import LLMError, OpenRouterLLM, Usage

URL = "https://openrouter.ai/api/v1/chat/completions"


def ok_body():
    return {"model": "openai/gpt-4.1-mini", "choices": [{"message": {"role": "assistant", "content": "",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "get_weather", "arguments": "{}"}}]}}],
            "usage": {"prompt_tokens": 900, "completion_tokens": 50, "total_tokens": 950, "cost": 0.0004}}


def test_requires_key():
    with pytest.raises(LLMError):
        OpenRouterLLM("x", api_key="")


@pytest.mark.asyncio
@respx.mock
async def test_chat_sends_tools_and_reads_usage():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=ok_body()))
    resp = await OpenRouterLLM("openai/gpt-4.1-mini", api_key="k").chat([{"role": "user", "content": "hi"}], [{"type": "function"}])
    sent = route.calls.last.request
    assert sent.headers["authorization"] == "Bearer k"
    body = __import__("json").loads(sent.content)
    assert body["tools"] and body["usage"] == {"include": True}
    assert resp.message["tool_calls"][0]["function"]["name"] == "get_weather"
    u = Usage()
    u.add(resp.usage, 1.2)
    assert u.total_tokens == 950 and u.cost_usd == 0.0004 and u.calls == 1


@pytest.mark.asyncio
@respx.mock
async def test_retries_on_503(monkeypatch):
    monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
    route = respx.post(URL).mock(side_effect=[httpx.Response(503, text="busy"), httpx.Response(200, json=ok_body())])
    resp = await OpenRouterLLM("m", api_key="k").chat([], [])
    assert route.call_count == 2 and resp.usage["total_tokens"] == 950


@pytest.mark.asyncio
@respx.mock
async def test_no_retry_on_401(monkeypatch):
    monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
    route = respx.post(URL).mock(return_value=httpx.Response(401, text="bad key"))
    with pytest.raises(LLMError, match="401"):
        await OpenRouterLLM("m", api_key="k").chat([], [])
    assert route.call_count == 1


async def _no_sleep(*_):
    return None


@pytest.mark.asyncio
@respx.mock
async def test_disconnects_are_retried_then_explained(monkeypatch):
    monkeypatch.setattr("app.llm.asyncio.sleep", _no_sleep)
    route = respx.post(URL).mock(side_effect=[httpx.RemoteProtocolError("Server disconnected without sending a response.")] * 5
                                 + [httpx.Response(200, json=ok_body())])
    assert (await OpenRouterLLM("m", api_key="k").chat([], [])).message  # пять обрывов подряд — всё равно ответ
    assert route.call_count == 6
    respx.post(URL).mock(side_effect=httpx.RemoteProtocolError("Server disconnected without sending a response."))
    with pytest.raises(LLMError, match="временно не отвечает"):
        await OpenRouterLLM("m", api_key="k").chat([], [])
