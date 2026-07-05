from __future__ import annotations

import logging

from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.db.repositories.search_api_config_repository import SearchApiConfigRepository
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft
from packages.search.tavily_client import SearchResultItem, TavilySearchClient, TavilySearchConfig


logger = logging.getLogger(__name__)


class SearchEvidence(BaseModel):
    query: str
    answer: str | None = None
    results: list[SearchResultItem] = Field(default_factory=list)
    error: str | None = None


class QuoteSearchContext(BaseModel):
    provider: str
    address_research: SearchEvidence | None = None
    market_research: SearchEvidence | None = None
    note: str = (
        "Search context is reference-only. It must not override deterministic quote_result amounts, "
        "zone rules, or manual_required decisions."
    )


def build_quote_search_context(
    db: Session,
    extraction: AIExtractedQuoteDraft,
    *,
    search_config_id: int | None = None,
) -> QuoteSearchContext | None:
    repository = SearchApiConfigRepository(db)
    record = repository.get_config(search_config_id) if search_config_id else repository.get_default_config()
    if record is None or not record.enabled:
        return None
    if record.provider != "tavily":
        logger.warning("Unsupported search provider skipped.", extra={"provider": record.provider})
        return None

    client = TavilySearchClient(
        TavilySearchConfig(
            api_key=repository.decrypt_api_key(record),
            base_url=record.base_url or "https://api.tavily.com",
        )
    )
    address_query = _build_address_query(extraction)
    market_query = _build_market_query(extraction)

    return QuoteSearchContext(
        provider=record.provider,
        address_research=_search(client, address_query, max_results=3) if address_query else None,
        market_research=_search(client, market_query, max_results=3),
    )


def _search(client: TavilySearchClient, query: str, *, max_results: int) -> SearchEvidence:
    response = client.search(query, max_results=max_results)
    return SearchEvidence(
        query=query,
        answer=response.answer,
        results=response.results,
        error=response.error,
    )


def _build_address_query(extraction: AIExtractedQuoteDraft) -> str | None:
    parts = [
        extraction.address_line,
        extraction.city,
        extraction.province,
        extraction.postal_code,
        "Canada address business residential rural delivery location",
    ]
    query = " ".join(part for part in parts if part)
    return query or None


def _build_market_query(extraction: AIExtractedQuoteDraft) -> str:
    location = " ".join(part for part in [extraction.city, extraction.province, extraction.postal_code] if part)
    return (
        f"Canada final mile LTL truck delivery {location} residential liftgate appointment remote area "
        "market conditions reference"
    ).strip()
