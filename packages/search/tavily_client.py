from __future__ import annotations

from time import perf_counter
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict, Field


class TavilySearchConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    api_key: str
    base_url: str = "https://api.tavily.com"
    timeout_seconds: int = Field(default=15, ge=1, le=60)


class SearchResultItem(BaseModel):
    title: str
    url: str
    content: str | None = None
    score: float | None = None


class SearchResponse(BaseModel):
    query: str
    answer: str | None = None
    results: list[SearchResultItem] = Field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None


class TavilySearchClient:
    def __init__(self, config: TavilySearchConfig):
        self.config = config

    def search(self, query: str, *, max_results: int = 5) -> SearchResponse:
        response_payload = SearchResponse(query=query)
        if not self.config.api_key:
            response_payload.error = "Tavily api_key is required."
            return response_payload

        started = perf_counter()
        try:
            with httpx.Client(timeout=self.config.timeout_seconds) as client:
                response = client.post(
                    f"{self.config.base_url.rstrip('/')}/search",
                    json={
                        "query": query,
                        "search_depth": "basic",
                        "max_results": max_results,
                        "include_answer": "basic",
                    },
                    headers={
                        "Authorization": f"Bearer {self.config.api_key}",
                        "Content-Type": "application/json",
                    },
                )
            response_payload.latency_ms = int((perf_counter() - started) * 1000)
            if response.status_code >= 400:
                response_payload.error = f"Tavily returned HTTP {response.status_code}: {_safe_error_body(response.text)}"
                return response_payload
            data = response.json()
            response_payload.answer = data.get("answer") if isinstance(data.get("answer"), str) else None
            response_payload.results = _parse_results(data)
            return response_payload
        except Exception as exc:
            response_payload.latency_ms = int((perf_counter() - started) * 1000)
            response_payload.error = f"{exc.__class__.__name__}: {exc}"
            return response_payload


def _parse_results(data: dict[str, Any]) -> list[SearchResultItem]:
    raw_results = data.get("results")
    if not isinstance(raw_results, list):
        return []

    results: list[SearchResultItem] = []
    for item in raw_results:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        url = item.get("url")
        if not isinstance(title, str) or not isinstance(url, str):
            continue
        score = item.get("score")
        results.append(
            SearchResultItem(
                title=title,
                url=url,
                content=item.get("content") if isinstance(item.get("content"), str) else None,
                score=score if isinstance(score, int | float) else None,
            )
        )
    return results


def _safe_error_body(text: str) -> str:
    compact = " ".join(text.split())
    if len(compact) > 300:
        return compact[:300] + "..."
    return compact
