from decimal import Decimal
import logging
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask, QuoteAuditLog
from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
from apps.api.db.repositories.quote_audit_repository import QuoteAuditRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.rate_rule_repository import RateRuleRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.db.session import get_db
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
from packages.quote_engine.engine import QuoteEngine
from packages.quote_engine.models import QuoteCalculationRequest, QuoteResult, ShipmentInput
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])
logger = logging.getLogger(__name__)


class ManualQuoteTaskUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: str | None = Field(default=None, min_length=1)
    assigned_to: str | None = None
    resolved_price_usd: Decimal | None = Field(default=None, ge=0)
    resolved_note: str | None = None


class AIAutoQuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    customer_message: str = Field(min_length=1)
    ai_config_id: int | None = None
    auto_submit_when_complete: bool = True


class AIAutoQuoteResponse(BaseModel):
    extraction: AIExtractedQuoteDraft
    quote_result: ZoneQuoteResult | None = None
    customer_reply: str | None = None
    internal_note: str | None = None
    missing_fields: list[str] = Field(default_factory=list)
    manual_review_required: bool


@router.post("/calculate", response_model=QuoteResult)
def calculate_quote(shipment: ShipmentInput, db: Session = Depends(get_db)) -> QuoteResult:
    candidate_rules = RateRuleRepository(db).list_candidate_rules(shipment)
    request = QuoteCalculationRequest(shipment=shipment, rate_rules=candidate_rules)
    return QuoteEngine().quote(request)


@router.post("/zone-calculate", response_model=ZoneQuoteResult)
def calculate_zone_quote(payload: ZoneQuoteRequest, db: Session = Depends(get_db)) -> ZoneQuoteResult:
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    result = ZoneQuoteEngine(ZoneRepository(db), pricing_config=pricing_config).quote(payload)
    _record_zone_quote_side_effects(db, payload, result)
    return result


@router.post("/ai-auto-quote", response_model=AIAutoQuoteResponse)
def calculate_ai_auto_quote(payload: AIAutoQuoteRequest, db: Session = Depends(get_db)) -> AIAutoQuoteResponse:
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
    if missing_fields:
        return AIAutoQuoteResponse(
            extraction=extraction,
            quote_result=None,
            customer_reply=build_follow_up_question(missing_fields),
            internal_note="Missing required fields. Zone Quote Engine was not called.",
            missing_fields=missing_fields,
            manual_review_required=True,
        )

    if not payload.auto_submit_when_complete:
        return AIAutoQuoteResponse(
            extraction=extraction,
            quote_result=None,
            customer_reply="字段已提取完成，请确认后提交系统报价。",
            internal_note="auto_submit_when_complete=false. Zone Quote Engine was not called.",
            missing_fields=[],
            manual_review_required=False,
        )

    zone_request = _zone_request_from_extraction(extraction)
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    quote_result = ZoneQuoteEngine(ZoneRepository(db), pricing_config=pricing_config).quote(zone_request)
    _record_zone_quote_side_effects(db, zone_request, quote_result)

    if quote_result.manual_review_required:
        return AIAutoQuoteResponse(
            extraction=extraction,
            quote_result=quote_result,
            customer_reply="这票需要人工确认后才能给客户报价，当前不要直接发送确定金额。",
            internal_note=f"Manual review required: {quote_result.matched_rule}",
            missing_fields=[],
            manual_review_required=True,
        )

    customer_reply = _build_guarded_sales_note(ai_client, quote_result)
    quote_result.sales_note = customer_reply
    return AIAutoQuoteResponse(
        extraction=extraction,
        quote_result=quote_result,
        customer_reply=customer_reply,
        internal_note="AI sales note was generated from locked quote_result only.",
        missing_fields=[],
        manual_review_required=False,
    )


@router.get("/audit/{quote_id}")
def get_quote_audit(quote_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    record = QuoteAuditRepository(db).get_by_quote_id(quote_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quote audit log not found.")
    return _audit_to_dict(record)


@router.get("/manual-tasks")
def list_manual_quote_tasks(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return [_manual_task_to_dict(task) for task in ManualQuoteTaskRepository(db).list_tasks()]


@router.patch("/manual-tasks/{task_id}")
def update_manual_quote_task(
    task_id: int,
    payload: ManualQuoteTaskUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    update = payload.model_dump(exclude_unset=True)
    task = ManualQuoteTaskRepository(db).update(task_id, **update)
    if task is None:
        raise HTTPException(status_code=404, detail="Manual quote task not found.")
    return _manual_task_to_dict(task)


def _record_zone_quote_side_effects(db: Session, payload: ZoneQuoteRequest, result: ZoneQuoteResult) -> None:
    try:
        QuoteAuditRepository(db).create_for_zone_quote(payload, result)
    except Exception:
        logger.exception("Failed to write zone quote audit log.", extra={"quote_id": result.quote_id})
        db.rollback()

    if not result.manual_review_required:
        return

    try:
        ManualQuoteTaskRepository(db).create_from_zone_quote(payload, result)
    except Exception:
        logger.exception("Failed to create manual quote task.", extra={"quote_id": result.quote_id})
        db.rollback()


def _audit_to_dict(record: QuoteAuditLog) -> dict[str, object]:
    return {
        "id": record.id,
        "quote_id": record.quote_id,
        "request_json": record.request_json,
        "result_json": record.result_json,
        "source_type": record.source_type,
        "postal_code": record.postal_code,
        "postal_prefix": record.postal_prefix,
        "city": record.city,
        "province": record.province,
        "origin": record.origin,
        "zone": record.zone,
        "billing_pallets": record.billing_pallets,
        "base_price_usd": _decimal_to_string(record.base_price_usd),
        "total_price_usd": _decimal_to_string(record.total_price_usd),
        "manual_review_required": record.manual_review_required,
        "risk_tags": record.risk_tags,
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _manual_task_to_dict(record: ManualQuoteTask) -> dict[str, object]:
    return {
        "id": record.id,
        "quote_id": record.quote_id,
        "reason": record.reason,
        "risk_tags": record.risk_tags,
        "request_json": record.request_json,
        "result_json": record.result_json,
        "status": record.status,
        "assigned_to": record.assigned_to,
        "resolved_price_usd": _decimal_to_string(record.resolved_price_usd),
        "resolved_note": record.resolved_note,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


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


def _build_guarded_sales_note(ai_client: OpenAICompatibleClient, quote_result: ZoneQuoteResult) -> str:
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
                        "allowed_actions": ["explain", "summarize", "warn_risk"],
                        "forbidden_actions": ["change_price", "invent_fee", "invent_market_rate"],
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
