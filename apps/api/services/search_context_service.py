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
    summary_zh: str | None = None
    results: list[SearchResultItem] = Field(default_factory=list)
    error: str | None = None


class QuoteSearchContext(BaseModel):
    provider: str
    address_research: SearchEvidence | None = None
    market_research: SearchEvidence | None = None
    note: str = (
        "搜索结果仅用于确认地址情况，不能覆盖系统价格表、Zone 规则或 manual_required 结论。"
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

    return QuoteSearchContext(
        provider=record.provider,
        address_research=_search(client, address_query, max_results=3, kind="address", extraction=extraction)
        if address_query
        else None,
        market_research=None,
    )


def _search(
    client: TavilySearchClient,
    query: str,
    *,
    max_results: int,
    kind: str,
    extraction: AIExtractedQuoteDraft,
) -> SearchEvidence:
    response = client.search(query, max_results=max_results)
    return SearchEvidence(
        query=query,
        answer=response.answer,
        summary_zh=_build_summary_zh(kind=kind, extraction=extraction, result_count=len(response.results), error=response.error),
        results=response.results,
        error=response.error,
    )


def _build_address_query(extraction: AIExtractedQuoteDraft) -> str | None:
    parts = [
        extraction.address_line,
        extraction.city,
        extraction.province,
        extraction.postal_code,
        "加拿大地址情况 查询 是否住宅 商业地址 小镇 偏远地区 卡车派送 卸货平台 请用中文总结",
    ]
    query = " ".join(part for part in parts if part)
    return query or None


def _build_summary_zh(
    *,
    kind: str,
    extraction: AIExtractedQuoteDraft,
    result_count: int,
    error: str | None,
) -> str:
    destination = "，".join(
        part
        for part in [
            extraction.address_line,
            extraction.city,
            extraction.province,
            extraction.postal_code,
        ]
        if part
    )
    destination = destination or "当前目的地"
    if error:
        return f"搜索验证失败：{error}。请人工确认 {destination} 的地址类型、偏远情况和派送限制。"
    if kind == "address":
        return (
            f"地址情况：已搜索 {destination} 的公开资料，返回 {result_count} 条来源。"
            "请重点确认该地址是否为住宅/私人地址、小镇或偏远地区，以及卡车是否可进入、是否有 dock/叉车、是否需要尾板或预约。"
            "搜索结果只作为人工判断线索，不会改变系统报价金额。"
        )
    return f"已搜索 {destination} 的公开资料，返回 {result_count} 条来源。"
