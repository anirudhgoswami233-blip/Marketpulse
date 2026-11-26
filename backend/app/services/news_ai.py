"""Optional LLM enrichment of news classification: category, materiality, and a one-line "why".

Budget-safe: every uncached headline in a request is classified in a single LLM call, and each result is
cached per headline (24h) so it's reused across requests. Grounded in the headline text; descriptive only,
never advice. Callers fall back to the keyword classifier (`news_impact`) when `LLM_API_KEY` is unset or a
call fails or returns anything unexpected.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.core.cache import CacheBackend
from app.core.llm import LLMClient, LLMError
from app.providers.base import NewsItem
from app.signals.news_impact import Materiality, NewsCategory

logger = logging.getLogger(__name__)

CACHE_TTL_S = 24 * 3600
MAX_WHY_LEN = 160
MAX_BATCH = 20

_CATEGORIES = {c.value for c in NewsCategory}
_MATERIALITIES = {m.value for m in Materiality}

SYSTEM = (
    "You classify stock-market news headlines. Reply with ONLY a JSON array, one object per headline in the "
    'same order, each exactly {"category": C, "materiality": M, "why": W} where C is one of '
    f"{sorted(_CATEGORIES)}, M is one of {sorted(_MATERIALITIES)}, and W is a factual description of why it "
    "matters in 12 words or fewer. Be descriptive only: never give advice, a recommendation, or a price "
    "target. No prose or code fences outside the JSON array."
)


@dataclass(frozen=True)
class LLMClass:
    category: str
    materiality: str
    why: str | None


def _key(headline: str) -> str:
    # Not security-sensitive: just a stable cache key for the headline text.
    return "mp:news-ai:" + hashlib.sha1(headline.encode("utf-8"), usedforsecurity=False).hexdigest()


def _coerce(obj: object) -> LLMClass | None:
    if not isinstance(obj, dict):
        return None
    category, materiality, why = obj.get("category"), obj.get("materiality"), obj.get("why")
    if category not in _CATEGORIES or materiality not in _MATERIALITIES:
        return None
    text = why.strip()[:MAX_WHY_LEN] if isinstance(why, str) and why.strip() else None
    return LLMClass(category=str(category), materiality=str(materiality), why=text)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0]
    return stripped.strip()


async def _classify_batch(client: LLMClient, items: Sequence[NewsItem]) -> list[LLMClass | None]:
    prompt = "\n".join(f"{i + 1}. {item.headline}" for i, item in enumerate(items))
    try:
        text = await client.complete(SYSTEM, prompt, max_tokens=800)
        data = json.loads(_strip_fences(text))
    except (LLMError, json.JSONDecodeError, ValueError) as exc:
        logger.info("News LLM enrichment failed: %s", exc)
        return [None] * len(items)
    if not isinstance(data, list):
        return [None] * len(items)
    return [_coerce(data[i]) if i < len(data) else None for i in range(len(items))]


async def enrich(client: LLMClient, cache: CacheBackend, items: Sequence[NewsItem]) -> dict[str, LLMClass]:
    """Map item id -> LLM classification. Cache hits are reused; the misses share one LLM call."""
    out: dict[str, LLMClass] = {}
    misses: list[NewsItem] = []
    for item in items[:MAX_BATCH]:
        raw = await cache.get(_key(item.headline))
        cached = None
        if raw:
            try:
                cached = _coerce(json.loads(raw))
            except (json.JSONDecodeError, ValueError):
                cached = None
        if cached is not None:
            out[item.id] = cached
        else:
            misses.append(item)
    if misses:
        for item, result in zip(misses, await _classify_batch(client, misses), strict=True):
            if result is not None:
                out[item.id] = result
                await cache.set(
                    _key(item.headline),
                    json.dumps(
                        {"category": result.category, "materiality": result.materiality, "why": result.why}
                    ),
                    CACHE_TTL_S,
                )
    return out
