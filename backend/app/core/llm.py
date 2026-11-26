"""Thin async client for the optional LLM features (Anthropic Messages API over httpx — no SDK dependency).

Used only when `LLM_API_KEY` is set, and strictly as an enhancement: callers must fall back to the
deterministic path (templates, keyword classifier) when it's absent or a call fails. The API key travels in
a header, never a URL or log.
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


class LLMError(Exception):
    """An LLM call failed or returned an unusable response. Callers fall back to the deterministic path."""


def build_client(timeout_s: float = 30.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=timeout_s)


class LLMClient:
    def __init__(self, client: httpx.AsyncClient, api_key: str, model: str) -> None:
        self._http = client
        self._key = api_key
        self.model = model

    async def complete(self, system: str, prompt: str, max_tokens: int = 1200) -> str:
        """Single-turn completion. Raises LLMError on any failure; never returns empty text."""
        try:
            response = await self._http.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": self._key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPError as exc:
            raise LLMError(f"LLM request failed: {exc}") from exc

        try:
            text = "".join(
                block.get("text", "")
                for block in data["content"]
                if isinstance(block, dict) and block.get("type") == "text"
            )
        except (KeyError, TypeError) as exc:
            raise LLMError(f"Unexpected LLM response shape: {exc}") from exc
        if not text.strip():
            raise LLMError("LLM returned empty text")
        return text
