import httpx
import pytest
import respx

from app.core.llm import ANTHROPIC_URL, LLMClient, LLMError


def _client() -> LLMClient:
    return LLMClient(httpx.AsyncClient(), "test-key", "claude-haiku-5-5")


async def test_complete_returns_text(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANTHROPIC_URL).respond(json={"content": [{"type": "text", "text": "Hello world"}]})
    assert await _client().complete("system", "hi") == "Hello world"


async def test_key_travels_in_header_not_the_url(respx_mock: respx.MockRouter) -> None:
    route = respx_mock.post(ANTHROPIC_URL).respond(json={"content": [{"type": "text", "text": "ok"}]})
    await _client().complete("system", "hi")
    request = route.calls.last.request
    assert request.headers["x-api-key"] == "test-key"
    assert "test-key" not in str(request.url)


async def test_http_error_raises_llm_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANTHROPIC_URL).respond(500, json={"error": "boom"})
    with pytest.raises(LLMError):
        await _client().complete("system", "hi")


async def test_unexpected_shape_raises_llm_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANTHROPIC_URL).respond(json={"unexpected": True})
    with pytest.raises(LLMError):
        await _client().complete("system", "hi")


async def test_empty_text_raises_llm_error(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANTHROPIC_URL).respond(json={"content": [{"type": "text", "text": "   "}]})
    with pytest.raises(LLMError):
        await _client().complete("system", "hi")
