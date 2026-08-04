from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.repositories.fcl_rate_card_repository import FCLQuoteConfigRepository
from apps.api.db.models import ManualQuoteTask, QuoteAuditLog, SalesQuoteRecord
from packages.quote_engine.fcl import (
    FCLQuoteDraft,
    FCLQuoteResult,
    _missing_fields,
    calculate_cargo,
    calculate_fcl_quote,
)
from apps.api.services.quote_workflow_service import record_event


logger = logging.getLogger(__name__)


class FCLAutoQuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    customer_id: int = Field(gt=0)
    confirmed_fields: FCLQuoteDraft

    @model_validator(mode="before")
    @classmethod
    def reject_legacy_form_fields(cls, values: object) -> object:
        if not isinstance(values, dict):
            return values
        legacy = {"contact", "confidence", "extraction_notes", "service_stages", "customer_name"}
        confirmed = values.get("confirmed_fields")
        if isinstance(confirmed, dict):
            forbidden = sorted(legacy.intersection(confirmed))
            if forbidden:
                raise ValueError(f"legacy FCL fields are not accepted: {', '.join(forbidden)}")
        return values


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
    idempotency_key: str | None = None,
) -> FCLAutoQuoteResponse:
    draft = payload.confirmed_fields.model_copy(update={"extraction_notes": ["structured_form"]})
    repository = FCLQuoteConfigRepository(db)
    config, config_version = repository.get_published()
    active_config = config
    quote_id = f"fcl_{uuid4().hex[:20]}"

    if active_config is None:
        raise HTTPException(status_code=409, detail="暂无已发布整柜报价配置，无法自动报价。")
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
            "request": payload.model_dump(mode="json"),
            "config": active_config.model_dump(mode="json"),
            "config_version": config_version,
        }
    )
    if actor is not None:
        _persist_fcl_submission(db, actor, payload, response, result, internal_snapshot)
    return response


def _persist_fcl_submission(db: Session, actor: CurrentActor, payload: FCLAutoQuoteRequest, response: FCLAutoQuoteResponse, result: FCLQuoteResult, snapshot: dict[str, Any]) -> None:
    workflow_status = "pending_review" if result.manual_review_required else "ready_to_send"
    record = SalesQuoteRecord(quote_type="fcl", quote_id=result.quote_id, actor_user_id=actor.user_id, actor_api_key_id=actor.api_key_id, actor_name=actor.name, actor_role=actor.role, status="manual_required" if result.manual_review_required else "quoted", workflow_status=workflow_status, customer_message=_summarize_draft(payload.confirmed_fields), customer_reply=response.customer_reply, request_json=payload.model_dump(mode="json"), result_json=response.model_dump(mode="json"), snapshot_json=snapshot, valid_until=result.quote_valid_until)
    db.add(record)
    db.flush()
    if result.manual_review_required:
        db.add(ManualQuoteTask(quote_id=result.quote_id, sales_quote_record_id=record.id, reason="；".join(result.manual_reasons), risk_tags=["fcl", *result.manual_reasons], request_json=payload.model_dump(mode="json"), result_json=snapshot, status="pending"))
    db.add(QuoteAuditLog(quote_id=result.quote_id, request_json=payload.model_dump(mode="json"), result_json=snapshot, source_type="fcl", manual_review_required=result.manual_review_required, risk_tags=["fcl", *result.manual_reasons]))
    actor_event = "auto_quote_ready" if not result.manual_review_required else "submitted_for_review"
    record_event(db, record, actor, actor_event, to_status=workflow_status, public_note="自动报价已生成" if workflow_status == "ready_to_send" else "已进入后台核价")
    db.commit()


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
