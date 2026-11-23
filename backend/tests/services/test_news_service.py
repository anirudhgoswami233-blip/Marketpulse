from datetime import UTC, datetime

from app.models import Symbol
from app.providers.base import NewsItem
from app.services import news_service
from tests.fakes import FakeProvider


def _symbol(exchange: str = "US") -> Symbol:
    return Symbol(symbol="AAPL", display_symbol="AAPL", description="APPLE INC", exchange_code=exchange)


def _news(headline: str, when: datetime, i: int = 0) -> NewsItem:
    return NewsItem(
        id=str(i),
        headline=headline,
        summary="",
        source="s",
        url=f"https://example.test/{i}",
        image_url=None,
        published_at=when,
        category=None,
        related_symbols=[],
    )


def test_pick_highlight_prefers_high_materiality_over_medium() -> None:
    t = datetime(2026, 10, 15, 12, tzinfo=UTC)
    items = [
        _news("Analysts upgrade Apple, raise price target", t, 0),  # rating -> medium
        _news("Apple beats estimates on record revenue", t, 1),  # earnings -> high
        _news("Apple names new retail chief", t, 2),  # other -> low (excluded)
    ]
    h = news_service.pick_highlight(_symbol(), items)
    assert h is not None
    assert h.category == "earnings" and h.materiality == "high"
    assert h.display_symbol == "AAPL" and h.name == "APPLE INC"


def test_pick_highlight_newest_breaks_ties() -> None:
    older = _news("Apple beats estimates", datetime(2026, 10, 14, tzinfo=UTC), 0)
    newer = _news("Apple quarterly revenue tops forecast", datetime(2026, 10, 16, tzinfo=UTC), 1)
    h = news_service.pick_highlight(_symbol(), [older, newer])
    assert h is not None and h.headline == "Apple quarterly revenue tops forecast"


def test_pick_highlight_none_when_only_low_materiality() -> None:
    items = [_news("Apple names new head of design", datetime(2026, 10, 15, tzinfo=UTC), 0)]
    assert news_service.pick_highlight(_symbol(), items) is None


async def test_top_material_headline_skips_non_us() -> None:
    provider = FakeProvider()
    provider.news = [_news("Some FX headline", datetime(2026, 10, 15, tzinfo=UTC), 0)]
    assert await news_service.top_material_headline(provider, _symbol("FX")) is None
    assert provider.news_calls == 0  # no provider call for non-US symbols


async def test_top_material_headline_reads_news_and_classifies() -> None:
    provider = FakeProvider()
    provider.news = [_news("Apple beats estimates on record revenue", datetime(2026, 10, 15, tzinfo=UTC), 0)]
    h = await news_service.top_material_headline(provider, _symbol(), datetime(2026, 10, 19, tzinfo=UTC))
    assert h is not None and h.materiality == "high" and h.category == "earnings"
