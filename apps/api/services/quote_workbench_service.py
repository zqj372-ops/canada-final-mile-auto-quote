"""Side-effect-free extraction and transactional, human-confirmed quotation."""
from __future__ import annotations

import logging
import re
from concurrent.futures import TimeoutError as FutureTimeout
from time import perf_counter
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import ManualQuoteTask, SalesQuoteRecord
from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
from apps.api.db.repositories.quote_audit_repository import QuoteAuditRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.sales_quote_record_repository import SalesQuoteRecordRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.services.address_validation_service import LocalAddressValidation, build_local_address_validation_from_extraction
from apps.api.services.ai_quote_service import _select_ai_config
from apps.api.services.hermes_diagnostic_service import enqueue_quote_diagnostic
from apps.api.services.quote_logic_explainer import attach_zone_quote_logic
from apps.api.services.quote_service import apply_learned_quote_if_available, enforce_origin_matrix_safety, enforce_zone_price_switch
from apps.api.services.search_context_service import QuoteSearchContext, build_quote_search_context
from apps.api.services.extraction_feedback_service import (
    CorrectionReason, build_extraction_feedback, digest, issue_extraction_receipt,
)
from packages.ai_assistant.extraction_runtime import ObservedAIClient, submit_extraction
from packages.ai_assistant.prompts import FIELD_EXTRACTION_SYSTEM_PROMPT, CARGO_EXTRACTION_SYSTEM_PROMPT, ADDRESS_EXTRACTION_SYSTEM_PROMPT
from packages.ai_assistant.fast_extractor import try_extract_locally
from packages.ai_assistant.model_client import OpenAICompatibleClient, config_from_record
from packages.ai_assistant.service_requirements import SERVICE_FIELDS, mentioned_service_fields
from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft, ALLOWED_PACKAGING_TYPES, QuoteExtractionError,
    apply_deterministic_extraction, extract_quote_draft, extract_quote_draft_with_agents, missing_required_fields,
)
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_lookup import get_province_from_postal_code
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult

logger = logging.getLogger(__name__)
QuoteField = Literal[
    "address_line", "postal_code", "city", "province", "cbm", "weight_kg", "piece_count",
    "packaging_type", "longest_side_cm", "address_type", "requires_liftgate",
    "requires_pallet_jack", "requires_appointment", "explicit_pallet_count", "is_stackable", "detention_minutes",
]
FieldSource = Literal["customer_original", "ai_extracted", "deterministic_extracted", "default_value", "human_edited"]


class AIExtractRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer_message: str = Field(min_length=1, max_length=20000)
    ai_config_id: int | None = None
    force_ai: bool = False
    strategy: Literal["single", "dual"] = "dual"
    budget_seconds: float = Field(default=30, ge=1, le=60)
    enable_search_context: bool = False
    search_config_id: int | None = None


class DraftError(BaseModel):
    field: str
    code: str


class AIExtractResponse(BaseModel):
    extraction: AIExtractedQuoteDraft
    field_provenance: dict[QuoteField, FieldSource]
    extraction_missing_fields: list[str]
    draft_validation_errors: list[DraftError]
    address_validation: LocalAddressValidation | None = None
    search_context: QuoteSearchContext | None = None
    extraction_mode: Literal["local", "ai", "fallback"]
    duration_ms: int
    extraction_metadata: dict[str, object] = Field(default_factory=dict)
    extraction_receipt: str | None = None


class ConfirmedQuote(ZoneQuoteRequest):
    requires_liftgate: bool
    requires_pallet_jack: bool
    requires_appointment: bool

    @model_validator(mode="after")
    def require_confirmed_fields(self):
        for field in ("address_line", "city", "province"):
            if not getattr(self, field):
                raise ValueError(f"{field}:required")
        if self.packaging_type not in ALLOWED_PACKAGING_TYPES:
            raise ValueError("packaging_type:invalid")
        if not re.fullmatch(r"[ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTVWXYZ] \d[ABCEGHJ-NPRSTVWXYZ]\d", self.postal_code):
            raise ValueError("postal_code:invalid")
        if self.province != get_province_from_postal_code(self.postal_code):
            raise ValueError("province:postal_province_mismatch")
        if self.packaging_type in {"woven_bag", "flexible_packaging"} and self.is_stackable is None:
            raise ValueError("is_stackable:required")
        return self


class ConfirmedCalculateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    customer_message: str = Field(min_length=1, max_length=20000)
    quote: ConfirmedQuote
    extraction_snapshot: AIExtractedQuoteDraft | None = None
    extraction_receipt: str | None = Field(default=None, max_length=20000)
    correction_reasons: dict[QuoteField, CorrectionReason] = Field(default_factory=dict)
    field_provenance: dict[QuoteField, FieldSource]
    supersedes_quote_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def require_provenance(self):
        for key, value in self.quote.model_dump().items():
            if value is not None and key not in self.field_provenance:
                raise ValueError(f"field_provenance.{key}:required")
        return self


class ConfirmedCalculateResponse(BaseModel):
    quote_result: ZoneQuoteResult
    sales_record_id: int
    manual_task_id: int | None = None
    superseded_quote_id: str | None = None
    superseded_task_id: int | None = None
    diagnostic_queued: bool


def draft_errors(extraction: AIExtractedQuoteDraft, address: LocalAddressValidation | None) -> list[DraftError]:
    values = {key: getattr(extraction, key) for key in ZoneQuoteRequest.model_fields}
    errors: list[DraftError] = []
    try:
        ConfirmedQuote.model_validate(values)
    except ValidationError as exc:
        for error in exc.errors():
            detail = error["msg"].removeprefix("Value error, ")
            field = str(error["loc"][0]) if error["loc"] else detail.split(":")[0]
            code = detail.split(":", 1)[1] if ":" in detail else error["type"]
            errors.append(DraftError(field=field, code=code))
    # City naming differences are advisory; the engine uses the postal lookup.
    if address and address.province_consistent is False:
        errors.append(DraftError(field="province", code="postal_lookup_mismatch"))
    return errors


def extract_for_workbench(db: Session, payload: AIExtractRequest, actor: CurrentActor | None = None) -> AIExtractResponse:
    started = perf_counter()
    sources: dict[str, str] = {}
    deadline = started + payload.budget_seconds
    observer = None
    model_metadata = None
    extraction = None if payload.force_ai else try_extract_locally(payload.customer_message)
    mode = "local"
    if extraction is None:
        repository = AIModelConfigRepository(db)
        config = _select_ai_config(repository, payload.ai_config_id)
        client = OpenAICompatibleClient(config_from_record(config, api_key=repository.decrypt_api_key(config)), deadline=deadline)
        observer = ObservedAIClient(client, deadline=deadline)
        model_metadata = {"config_id": config.id, "provider": config.provider, "model_name": config.model_name}
        try:
            if payload.strategy == "single":
                future = submit_extraction(extract_quote_draft, payload.customer_message, observer)
                try:
                    extraction = future.result(timeout=max(0, deadline - perf_counter()))
                finally:
                    future.cancel()
                sources.update({key: "ai_extracted" for key in ZoneQuoteRequest.model_fields if getattr(extraction, key) is not None})
            else:
                extraction = extract_quote_draft_with_agents(payload.customer_message, observer, provenance=sources, deadline=deadline)
            mode = "ai"
        except (QuoteExtractionError, FutureTimeout, RuntimeError):
            extraction = apply_deterministic_extraction(AIExtractedQuoteDraft(), payload.customer_message)
            extraction.validation_notes.append("model_unavailable_review_fields")
            mode = "fallback"
    # Workbench policy: omitted services are not needed. Explicit uncertainty
    # or conflicting instructions still require confirmation.
    mentioned_services = mentioned_service_fields(payload.customer_message)
    for field in SERVICE_FIELDS:
        if field not in mentioned_services:
            setattr(extraction, field, False)
            sources[field] = "default_value"
    provenance = {
        key: sources.get(key, "deterministic_extracted")
        for key in ZoneQuoteRequest.model_fields if getattr(extraction, key) is not None
    }
    extraction.missing_fields = sorted(missing_required_fields(extraction))
    address = build_local_address_validation_from_extraction(db, extraction)
    search = (build_quote_search_context(db, extraction, search_config_id=payload.search_config_id)
              if payload.enable_search_context else None)
    duration_ms = round((perf_counter() - started) * 1000)
    metadata = {"parser_version": "2026-10-13.1", "strategy": "local" if mode == "local" else payload.strategy,
                "schema_hash": digest(AIExtractedQuoteDraft.model_json_schema()),
                "prompt_hash": digest([FIELD_EXTRACTION_SYSTEM_PROMPT, CARGO_EXTRACTION_SYSTEM_PROMPT, ADDRESS_EXTRACTION_SYSTEM_PROMPT]),
                "model": model_metadata, "duration_ms": duration_ms, "budget_seconds": payload.budget_seconds,
                "outcome": mode, **(observer.snapshot() if observer else {"model_calls": 0, "repair_calls": 0, "calls": []})}
    receipt = issue_extraction_receipt(payload.customer_message, extraction.model_dump(mode="json"), metadata, actor)
    return AIExtractResponse(
        extraction=extraction, field_provenance=provenance,
        extraction_missing_fields=extraction.missing_fields,
        draft_validation_errors=draft_errors(extraction, address),
        address_validation=address, search_context=search, extraction_mode=mode,
        duration_ms=duration_ms, extraction_metadata=metadata, extraction_receipt=receipt,
    )


def _lock_superseded_task(db: Session, quote_id: str, actor: CurrentActor):
    record = db.scalars(select(SalesQuoteRecord).where(SalesQuoteRecord.scope_kind == "legacy").where(SalesQuoteRecord.quote_id == quote_id)
                        .order_by(SalesQuoteRecord.id.desc()).with_for_update()).first()
    task = db.scalars(select(ManualQuoteTask).where(ManualQuoteTask.scope_kind == "legacy").where(ManualQuoteTask.quote_id == quote_id)
                      .order_by(ManualQuoteTask.id.desc()).with_for_update()).first()
    owned = record and (
        actor.role in {"admin", "operator"}
        or (actor.user_id is not None and record.actor_user_id == actor.user_id)
        or (actor.api_key_id is not None and record.actor_api_key_id == actor.api_key_id)
    )
    if not owned or not task or task.status != "pending" or record.status != "manual_required":
        raise HTTPException(status_code=409, detail="旧人工任务不存在、已处理或无权替代，请新建报价。")
    return record, task


def calculate_confirmed(db: Session, payload: ConfirmedCalculateRequest, actor: CurrentActor) -> ConfirmedCalculateResponse:
    quote = payload.quote
    feedback = build_extraction_feedback(raw=payload.customer_message,
        snapshot=payload.extraction_snapshot.model_dump(mode="json") if payload.extraction_snapshot else None,
        confirmed=quote.model_dump(mode="json"), receipt=payload.extraction_receipt,
        reasons=payload.correction_reasons, actor=actor)
    try:
        address = build_local_address_validation_from_extraction(db, AIExtractedQuoteDraft(**quote.model_dump()))
        if address.province_consistent is False:
            raise HTTPException(status_code=422, detail={
                "message": "省份与邮编记录不一致，请核对后再报价。",
                "preferred_city": address.preferred_city, "province": address.province,
            })
        old_record, old_task = (_lock_superseded_task(db, payload.supersedes_quote_id, actor)
                                if payload.supersedes_quote_id else (None, None))
        pricing = QuoteRuleConfigRepository(db).get_zone_pricing_config()
        result = ZoneQuoteEngine(ZoneRepository(db), pricing_config=pricing).quote(quote)
        # A successful matrix quote remains authoritative in the new workflow.
        if result.manual_review_required:
            result = apply_learned_quote_if_available(db, quote, result, commit=False, pricing_config=pricing)
        result = enforce_origin_matrix_safety(quote, result)
        result = enforce_zone_price_switch(pricing, result)
        result = attach_zone_quote_logic(quote, result)
        if not result.manual_review_required and result.total_price_usd is None:
            raise ValueError("Quote Engine returned no price for a successful quote")

        if old_task is not None:
            old_task.status = "cancelled"
            old_task.resolved_note = f"superseded_by_quote_id={result.quote_id}"
            old_task.result_json = {**old_task.result_json, "superseded_by_quote_id": result.quote_id}
            old_record.status = "superseded"
            old_record.result_json = {**old_record.result_json, "superseded_by_quote_id": result.quote_id}

        audit = QuoteAuditRepository(db).create_for_zone_quote(quote, result, commit=False)
        audit.request_json = {**quote.model_dump(mode="json"),
                              "customer_message": payload.customer_message,
                              "field_provenance": payload.field_provenance,
                              "extraction_feedback": feedback,
                              "extraction_snapshot": payload.extraction_snapshot.model_dump(mode="json") if payload.extraction_snapshot else None}
        task = (ManualQuoteTaskRepository(db).create_from_zone_quote(quote, result, commit=False)
                if result.manual_review_required else None)
        record = SalesQuoteRecordRepository(db).create_record(
            actor=actor, quote_id=result.quote_id,
            status="manual_required" if result.manual_review_required else "quoted",
            customer_message=payload.customer_message, customer_reply=result.sales_note,
            request_json=payload.model_dump(mode="json"),
            result_json={"quote_result": result.model_dump(mode="json"),
                         "extraction": quote.model_dump(mode="json"),
                         "manual_review_required": result.manual_review_required,
                         "customer_reply": result.sales_note, "missing_fields": []},
            commit=False,
        )
        queued = enqueue_quote_diagnostic(db, quote, result, raw_input=payload.customer_message,
                                          extraction=payload.extraction_snapshot.model_dump(mode="json") if payload.extraction_snapshot else None,
                                          source="confirmed_quote", commit=False)
        record_id, task_id, old_task_id = record.id, task.id if task else None, old_task.id if old_task else None
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception as exc:
        db.rollback()
        logger.exception("Confirmed quote transaction failed")
        raise HTTPException(status_code=503, detail="报价未保存，请稍后重试；本次没有生成可发送报价。") from exc

    return ConfirmedCalculateResponse(
        quote_result=result, sales_record_id=record_id, manual_task_id=task_id,
        superseded_quote_id=payload.supersedes_quote_id, superseded_task_id=old_task_id,
        diagnostic_queued=queued is not None,
    )
