"""FRED adapter for macro series (rates, inflation). FRED only accepts its key as a query parameter,
so the transport keeps URLs out of error messages and logging silences httpx's URL logging."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.cache import CacheBackend, cached
from app.core.errors import NoDataError, ProviderError
from app.core.ratelimit import RateLimiter
from app.providers.base import MacroDataProvider, MacroObservation, MacroSeries
from app.providers.http import ProviderTransport

BASE_URL = "https://api.stlouisfed.org/fred"

TTL_SERIES = 12 * 3600


def build_client(timeout_s: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE_URL, timeout=timeout_s)


class FredProvider(MacroDataProvider):
    name = "fred"

    def __init__(
        self, client: httpx.AsyncClient, limiter: RateLimiter, cache: CacheBackend, api_key: str
    ) -> None:
        self.cache = cache
        self._api_key = api_key
        self._http = ProviderTransport(self.name, client, limiter)

    async def _get(self, path: str, params: dict[str, str | int]) -> dict[str, Any]:
        payload = await self._http.get_json(path, {**params, "api_key": self._api_key, "file_type": "json"})
        if not isinstance(payload, dict):
            raise ProviderError(self.name, f"unexpected response shape from {path}")
        return payload

    @cached(ttl=TTL_SERIES)
    async def get_series(self, series_id: str, start: date) -> MacroSeries:
        info = await self._get("/series", {"series_id": series_id})
        series_list = info.get("seriess") or []
        if not series_list:
            raise NoDataError(self.name, f"unknown series {series_id}")
        meta = series_list[0]
        raw = await self._get(
            "/series/observations", {"series_id": series_id, "observation_start": start.isoformat()}
        )
        observations = []
        for item in raw.get("observations") or []:
            # FRED marks missing observations with "."
            value = _dec(item.get("value"))
            if value is None:
                continue
            try:
                observations.append(MacroObservation(date=date.fromisoformat(item["date"]), value=value))
            except (KeyError, ValueError):
                continue
        return MacroSeries(
            series_id=series_id,
            title=meta.get("title") or series_id,
            units=meta.get("units_short") or meta.get("units") or "",
            frequency=meta.get("frequency_short") or meta.get("frequency") or "",
            last_updated=_parse_updated(meta.get("last_updated")),
            observations=observations,
        )


def _dec(value: Any) -> Decimal | None:
    if value in (None, "", "."):
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _parse_updated(value: Any) -> datetime | None:
    # e.g. "2026-10-01 08:01:02-05"
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value + ":00" if len(value) == 22 else value)
    except ValueError:
        return None
