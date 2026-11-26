import json
from datetime import UTC, datetime

import httpx
import respx

from app.core.cache import MemoryCache
from app.core.llm import ANTHROPIC_URL, LLMClient
from app.providers.base import NewsItem
from app.services import news_ai


def _news(headline: str, i: int) -> NewsItem:
    return NewsItem(
        id=str(i),
        headline=headline,
        summary="",
        source="s",
        url=f"https://example.test/{i}",
        image_url=None,
        published_at=datetime(2026, 10, 15, tzinfo=UTC),
        category=None,
        related_symbols=[],
    )


def _response(array: list[dict[str, str]]) -> dict[str, object]:
    return {"content": [{"type": "text", "text": json.dumps(array)}]}


def _client() -> LLMClient:
    return LLMClient(httpx.AsyncClient(), "k", "claude-haiku-5-5")


async def test_enrich_classifies_and_caches_per_headline(respx_mock: respx.MockRouter) -> None:
    items = [_news("Apple beats estimates", 0), _news("Analysts upgrade Apple", 1)]
    route = respx_mock.post(ANTHROPIC_URL).respond(
        json=_response(
            [
                {"category": "earnings", "materiality": "high", "why": "Beat profit estimates"},
                {"category": "rating_change", "materiality": "medium", "why": "Analyst upgrade"},
            ]
        )
    )
    cache = MemoryCache()
    out = await news_ai.enrich(_client(), cache, items)
    assert out["0"].category == "earnings" and out["0"].why == "Beat profit estimates"
    assert out["1"].category == "rating_change" and out["1"].materiality == "medium"

    # Second call: everything is cached, so no further LLM request is made.
    again = await news_ai.enrich(_client(), cache, items)
    assert again["0"].category == "earnings"
    assert route.call_count == 1


async def test_enrich_falls_back_on_unparseable_response(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANTHROPIC_URL).respond(json={"content": [{"type": "text", "text": "not json"}]})
    assert await news_ai.enrich(_client(), MemoryCache(), [_news("headline", 0)]) == {}


async def test_enrich_drops_items_with_invalid_labels(respx_mock: respx.MockRouter) -> None:
    respx_mock.post(ANTHROPIC_URL).respond(
        json=_response([{"category": "nonsense", "materiality": "high", "why": "x"}])
    )
    assert await news_ai.enrich(_client(), MemoryCache(), [_news("headline", 0)]) == {}
