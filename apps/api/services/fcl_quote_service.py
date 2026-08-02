from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import QuoteAuditLog
from apps.api.db.repositories.fcl_rate_card_repository import FCLQuoteConfigRepository
from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
from apps.api.db.repositories.sales_quote_record_repository import SalesQuoteRecordRepository
from packages.ai_assistant.fcl_quote_extractor import extract_fcl_draft
from packages.ai_assistant.model_client import OpenAICompatibleClient, config_from_record
from packages.quote_engine.fcl import (
    FCLQuoteDraft,
    FCLQuoteResult,
    _missing_fields,
    calculate_cargo,
    calculate_fcl_quote,
    default_fcl_quote_config,
)
from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository


logger = logging.getLogger(__name__)


class FCLAutoQuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    raw_message: str = Field(default="", max_length=20000)
    confirmed_fields: FCLQuoteDraft = Field(default_factory=FCLQuoteDraft)
    auto_submit_when_complete: bool = True
    ai_config_id: int | None = None


class FCLAutoQuoteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extraction: FCLQuoteDraft
    cargo_recalculation: object
    quote_result: FCLQuoteResult | None = None
    customer_reply: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    manual_review_required: bool


def calculate_fcl_auto_quote(
    db: Session,
    payload: FCLAutoQuoteRequest,
    actor: CurrentActor | None = None,
) -> FCLAutoQuoteResponse:
    source_message = payload.raw_message.strip() or _summarize_draft(payload.confirmed_fields)
    if payload.raw_message.strip():
        draft = extract_fcl_draft(payload.raw_message, _optional_ai_client(db, payload.ai_config_id))
    else:
        draft = FCLQuoteDraft(extraction_notes=["form_filled_manually"])
    draft = _merge_confirmed_fields(draft, payload.confirmed_fields)
    repository = FCLQuoteConfigRepository(db)
    config, config_version = repository.get_published()
    active_config = config or default_fcl_quote_config()
    quote_id = f"fcl_{uuid4().hex[:20]}"

    if not payload.auto_submit_when_complete:
        cargo = calculate_cargo(draft)
        missing = _missing_fields(draft, active_config.required_fields, cargo)
        response = FCLAutoQuoteResponse(
            extraction=draft,
            cargo_recalculation=cargo,
            quote_result=None,
            customer_reply="字段已提取，请确认后提交整柜报价。",
            missing_fields=missing,
            manual_review_required=False,
        )
        return response

    rate_cards = repository.list_rate_cards(status="published")
    result, internal_snapshot = calculate_fcl_quote(
        draft,
        active_config,
        rate_cards,
        quote_id=quote_id,
        config_version=config_version,
    )
    missing_fields = sorted(
        reason.split(":", 1)[1]
        for reason in result.manual_reasons
        if reason.startswith("missing:")
    )
    response = FCLAutoQuoteResponse(
        extraction=result.normalized_input,
        cargo_recalculation=result.cargo_calculation,
        quote_result=result,
        customer_reply=result.customer_reply,
        missing_fields=missing_fields,
        manual_review_required=result.manual_review_required,
    )
    internal_snapshot.update(
        {
            "raw_message": payload.raw_message,
            "request": payload.model_dump(mode="json"),
            "config": active_config.model_dump(mode="json"),
            "config_version": config_version,
        }
    )
    if result.manual_review_required:
        _record_manual_task(db, result, payload, internal_snapshot)
    _record_fcl_audit(db, result, payload, internal_snapshot)
    return _record_sales_response(
        db,
        actor,
        payload,
        response,
        quote_id=quote_id,
        snapshot=internal_snapshot,
        customer_message=source_message,
    )


def _optional_ai_client(db: Session, config_id: int | None) -> Any:
    repository = AIModelConfigRepository(db)
    record = repository.get_config(config_id) if config_id is not None else repository.get_default_config()
    if record is None or not record.enabled:
        return None
    try:
        return OpenAICompatibleClient(
            config_from_record(record, api_key=repository.decrypt_api_key(record))
        )
    except Exception:
        logger.warning("FCL AI extractor unavailable; deterministic extraction will be used.")
        return None


def _merge_confirmed_fields(draft: FCLQuoteDraft, confirmed: FCLQuoteDraft) -> FCLQuoteDraft:
    merged = draft.model_dump()
    for key, value in confirmed.model_dump().items():
        if value not in (None, "", [], {}) and key not in {"confidence", "extraction_notes"}:
            merged[key] = value
    return FCLQuoteDraft.model_validate(merged)


def _record_manual_task(db: Session, result: FCLQuoteResult, payload: FCLAutoQuoteRequest, snapshot: dict[str, Any]) -> None:
    try:
        ManualQuoteTaskRepository(db).create_ai_review_task(
            quote_id=result.quote_id,
            reason="；".join(result.manual_reasons),
            risk_tags=["fcl", "fcl_manual_required", *result.manual_reasons],
            request_json=payload.model_dump(mode="json"),
            result_json=snapshot,
        )
    except Exception:
        logger.exception("Failed to create FCL manual review task", extra={"quote_id": result.quote_id})
        db.rollback()


def _record_fcl_audit(db: Session, result: FCLQuoteResult, payload: FCLAutoQuoteRequest, snapshot: dict[str, Any]) -> None:
    try:
        db.add(
            QuoteAuditLog(
                quote_id=result.quote_id,
                request_json=payload.model_dump(mode="json"),
                result_json=snapshot,
                source_type="fcl",
                manual_review_required=result.manual_review_required,
                risk_tags=["fcl", *result.manual_reasons],
            )
        )
        db.commit()
    except Exception:
        logger.exception("Failed to write FCL quote audit", extra={"quote_id": result.quote_id})
        db.rollback()


def _record_sales_response(
    db: Session,
    actor: CurrentActor | None,
    payload: FCLAutoQuoteRequest,
    response: FCLAutoQuoteResponse,
    *,
    quote_id: str,
    snapshot: dict[str, Any],
    customer_message: str | None = None,
) -> FCLAutoQuoteResponse:
    if actor is None:
        return response
    try:
        SalesQuoteRecordRepository(db).create_record(
            actor=actor,
            quote_type="fcl",
            quote_id=quote_id,
            status="manual_required" if response.manual_review_required else "quoted",
            customer_message=customer_message or payload.raw_message,
            customer_reply=response.customer_reply,
            request_json=payload.model_dump(mode="json"),
            result_json=response.model_dump(mode="json"),
            snapshot_json=snapshot,
        )
    except Exception:
        logger.exception("Failed to write FCL sales quote record", extra={"quote_id": quote_id})
        db.rollback()
    return response


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _summarize_draft(draft: FCLQuoteDraft) -> str:
    parts: list[str] = []
    if draft.pol:
        parts.append(f"POL {draft.pol}")
    if draft.pod:
        parts.append(f"POD {draft.pod}")
    if draft.containers:
        parts.append("、".join(f"{item.container_type} x{item.quantity}" for item in draft.containers))
    if draft.service_scope:
        parts.append(draft.service_scope)
    if draft.cargo_name:
        parts.append(f"货名 {draft.cargo_name}")
    return "；".join(parts) or "AI 整柜报价（表单填写）"
