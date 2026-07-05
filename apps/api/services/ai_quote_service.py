from __future__ import annotations

import json
import logging

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.services.notification_service import notify_ai_missing_fields, notify_ai_quote_success
from apps.api.services.quote_service import record_zone_quote_side_effects, try_wecom_notify
from apps.api.services.search_context_service import QuoteSearchContext, build_quote_search_context
from packages.ai_assistant.model_client import AIMessage, OpenAICompatibleClient, config_from_record
from packages.ai_assistant.output_guard import validate_zone_ai_output
from packages.ai_assistant.prompts import SALES_NOTE_SYSTEM_PROMPT
from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft,
    QuoteExtractionError,
    build_follow_up_question,
    extract_quote_draft,
    missing_required_fields,
)
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


logger = logging.getLogger(__name__)


class AIAutoQuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    customer_message: str = Field(min_length=1)
    ai_config_id: int | None = None
    auto_submit_when_complete: bool = True
    notify_wecom: bool = False
    wecom_bot_id: int | None = None
    enable_search_context: bool = False
    search_config_id: int | None = None


class AIAutoQuoteResponse(BaseModel):
    extraction: AIExtractedQuoteDraft
    quote_result: ZoneQuoteResult | None = None
    customer_reply: str | None = None
    internal_note: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    manual_review_required: bool
    search_context: QuoteSearchContext | None = None


def calculate_ai_auto_quote(db: Session, payload: AIAutoQuoteRequest) -> AIAutoQuoteResponse:
    config_repository = AIModelConfigRepository(db)
    config_record = _select_ai_config(config_repository, payload.ai_config_id)
    ai_client = OpenAICompatibleClient(
        config_from_record(config_record, api_key=config_repository.decrypt_api_key(config_record))
    )

    try:
        extraction = extract_quote_draft(payload.customer_message, ai_client)
    except QuoteExtractionError as exc:
        raise HTTPException(status_code=502, detail=f"AI field extraction failed: {exc}") from exc

    missing_fields = sorted(set(extraction.missing_fields) | missing_required_fields(extraction))
    extraction.missing_fields = missing_fields
    search_context = _optional_search_context(db, extraction, payload)
    if missing_fields:
        customer_reply = build_follow_up_question(missing_fields)
        if payload.notify_wecom:
            try_wecom_notify(
                "ai_missing_fields",
                lambda: notify_ai_missing_fields(
                    db,
                    customer_reply=customer_reply,
                    missing_fields=missing_fields,
                    bot_id=payload.wecom_bot_id,
                ),
                "missing-fields",
            )
        return AIAutoQuoteResponse(
            extraction=extraction,
            quote_result=None,
            customer_reply=customer_reply,
            internal_note="Missing required fields. Zone Quote Engine was not called.",
            missing_fields=missing_fields,
            manual_review_required=True,
            search_context=search_context,
        )

    if not payload.auto_submit_when_complete:
        return AIAutoQuoteResponse(
            extraction=extraction,
            quote_result=None,
            customer_reply="字段已提取完成，请确认后提交系统报价。",
            internal_note="auto_submit_when_complete=false. Zone Quote Engine was not called.",
            missing_fields=[],
            manual_review_required=False,
            search_context=search_context,
        )

    zone_request = _zone_request_from_extraction(extraction)
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    quote_result = ZoneQuoteEngine(ZoneRepository(db), pricing_config=pricing_config).quote(zone_request)
    record_zone_quote_side_effects(db, zone_request, quote_result, manual_wecom_bot_id=payload.wecom_bot_id)

    if quote_result.manual_review_required:
        return AIAutoQuoteResponse(
            extraction=extraction,
            quote_result=quote_result,
            customer_reply="这票需要人工确认后才能给客户报价，当前不要直接发送确定金额。",
            internal_note=f"Manual review required: {quote_result.matched_rule}",
            missing_fields=[],
            manual_review_required=True,
            search_context=search_context,
        )

    customer_reply = (
        _build_guarded_sales_note(ai_client, quote_result, search_context=search_context)
        if search_context
        else _build_guarded_sales_note(ai_client, quote_result)
    )
    quote_result.sales_note = customer_reply
    response = AIAutoQuoteResponse(
        extraction=extraction,
        quote_result=quote_result,
        customer_reply=customer_reply,
        internal_note="AI sales note was generated from locked quote_result only.",
        missing_fields=[],
        manual_review_required=False,
        search_context=search_context,
    )
    if payload.notify_wecom:
        try_wecom_notify(
            "ai_quote",
            lambda: notify_ai_quote_success(db, response=response, bot_id=payload.wecom_bot_id),
            quote_result.quote_id,
        )
    return response


def _select_ai_config(repository: AIModelConfigRepository, config_id: int | None):
    if config_id is not None:
        record = repository.get_config(config_id)
        if record is None:
            raise HTTPException(status_code=404, detail="AI model config not found.")
        if not record.enabled:
            raise HTTPException(status_code=400, detail="AI model config is disabled.")
        return record

    record = repository.get_default_config()
    if record is None:
        raise HTTPException(status_code=400, detail="No default AI model config is available.")
    return record


def _optional_search_context(
    db: Session,
    extraction: AIExtractedQuoteDraft,
    payload: AIAutoQuoteRequest,
) -> QuoteSearchContext | None:
    if not payload.enable_search_context:
        return None
    try:
        return build_quote_search_context(db, extraction, search_config_id=payload.search_config_id)
    except Exception as exc:
        logger.warning("Search context failed.", extra={"error": str(exc)})
        return QuoteSearchContext(provider="unknown", note=f"Search context failed: {exc.__class__.__name__}")


def _zone_request_from_extraction(extraction: AIExtractedQuoteDraft) -> ZoneQuoteRequest:
    try:
        return ZoneQuoteRequest(
            address_line=extraction.address_line,
            postal_code=extraction.postal_code or "",
            city=extraction.city,
            province=extraction.province,
            cbm=extraction.cbm,
            weight_kg=extraction.weight_kg,
            piece_count=extraction.piece_count,
            packaging_type=extraction.packaging_type or "unknown",
            longest_side_cm=extraction.longest_side_cm,
            explicit_pallet_count=extraction.explicit_pallet_count,
            is_stackable=extraction.is_stackable,
            address_type=extraction.address_type,
            requires_liftgate=extraction.requires_liftgate,
            requires_pallet_jack=extraction.requires_pallet_jack,
            requires_appointment=extraction.requires_appointment,
            detention_minutes=extraction.detention_minutes,
        )
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Extracted quote fields failed validation: {exc}") from exc


def _build_guarded_sales_note(
    ai_client: OpenAICompatibleClient,
    quote_result: ZoneQuoteResult,
    *,
    search_context: QuoteSearchContext | None = None,
) -> str:
    fallback = quote_result.sales_note or "Quote result is locked by the deterministic quote engine."
    response = ai_client.complete(
        [
            AIMessage(role="system", content=SALES_NOTE_SYSTEM_PROMPT),
            AIMessage(
                role="user",
                content=json.dumps(
                    {
                        "price_locked": True,
                        "quote_result": quote_result.model_dump(mode="json"),
                        "external_search_context": search_context.model_dump(mode="json") if search_context else None,
                        "allowed_actions": ["explain", "summarize", "warn_risk", "mention_reference_only_search_context"],
                        "forbidden_actions": [
                            "change_price",
                            "invent_fee",
                            "invent_market_rate",
                            "use_search_result_as_quote_price",
                        ],
                    },
                    ensure_ascii=False,
                ),
            ),
        ]
    )
    if response.error or not response.content.strip():
        return fallback

    guard = validate_zone_ai_output(quote_result, response.content)
    if not guard.allowed:
        logger.warning("Blocked AI sales note output.", extra={"quote_id": quote_result.quote_id, "reason": guard.reason})
        return fallback
    return response.content.strip()
