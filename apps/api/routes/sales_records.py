from decimal import Decimal

from datetime import UTC, datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import ALL_ROLES, AI_QUOTE_WRITE_ROLES, MANUAL_TASK_WRITE_ROLES, CurrentActor, require_roles
from apps.api.db.repositories.sales_quote_record_repository import (
    SalesQuoteRecordRepository,
    sales_quote_record_to_dict,
)
from apps.api.db.session import get_db
from apps.api.services.quote_workflow_service import AdditionalInfoRequest, MarkSentRequest, OutcomeRequest, assert_sales_owner, public_record, transition
from apps.api.db.models import ManualQuoteTask
from apps.api.db.repositories.fcl_rate_card_repository import FCLQuoteConfigRepository
from packages.quote_engine.fcl import calculate_fcl_quote


router = APIRouter(prefix="/quotes", tags=["sales-records"])


class ManualPriceOverrideRequest(BaseModel):
    total_price_usd: Decimal = Field(ge=0)
    override_note: str = Field(min_length=2, max_length=1000)
    customer_reply: str | None = Field(default=None, max_length=5000)
    confirmed: bool = False


@router.get("/sales-records")
def list_sales_quote_records(
    status: str | None = Query(default=None),
    limit: int = 50,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*ALL_ROLES)),
) -> list[dict[str, object]]:
    records = SalesQuoteRecordRepository(db).list_records(actor=actor, status=status, limit=limit)
    return [public_record(db, record) for record in records]


@router.get("/sales-records/{record_id}")
def get_sales_quote_record(record_id: int, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*ALL_ROLES))) -> dict[str, object]:
    record = SalesQuoteRecordRepository(db).get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sales quote record not found.")
    assert_sales_owner(record, actor)
    return public_record(db, record)


@router.post("/sales-records/{record_id}/mark-sent")
def mark_sales_quote_sent(record_id: int, payload: MarkSentRequest, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES))) -> dict[str, object]:
    record = SalesQuoteRecordRepository(db).get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sales quote record not found.")
    assert_sales_owner(record, actor)
    record.sent_at = datetime.now(UTC)
    record.sent_snapshot_json = dict(record.snapshot_json or {})
    transition(db, record, actor, "sent", "sales_marked_sent", public_note="销售已发送客户报价", metadata={"channel": payload.channel, "note": payload.note})
    db.commit()
    return public_record(db, record)


@router.post("/sales-records/{record_id}/outcome")
def record_sales_quote_outcome(record_id: int, payload: OutcomeRequest, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES))) -> dict[str, object]:
    record = SalesQuoteRecordRepository(db).get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sales quote record not found.")
    assert_sales_owner(record, actor)
    transition(db, record, actor, payload.outcome, "customer_outcome", public_note=payload.note)
    db.commit()
    return public_record(db, record)


@router.post("/sales-records/{record_id}/additional-info")
def submit_sales_additional_info(record_id: int, payload: AdditionalInfoRequest, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES))) -> dict[str, object]:
    record = SalesQuoteRecordRepository(db).get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sales quote record not found.")
    assert_sales_owner(record, actor)
    if record.workflow_status != "needs_sales_info" or record.quote_type != "fcl":
        raise HTTPException(status_code=409, detail="当前报价不在待补资料状态。")
    config, version = FCLQuoteConfigRepository(db).get_published()
    if config is None:
        raise HTTPException(status_code=409, detail="暂无已发布整柜报价配置。")
    task = db.scalar(select(ManualQuoteTask).where(ManualQuoteTask.sales_quote_record_id == record.id))
    cards = FCLQuoteConfigRepository(db).list_rate_cards(status="published")
    result, snapshot = calculate_fcl_quote(payload.confirmed_fields, config, cards, quote_id=record.quote_id or "", config_version=version)
    record.revision += 1
    record.request_json = {**(record.request_json or {}), "confirmed_fields": payload.confirmed_fields.model_dump(mode="json"), "revision": record.revision}
    record.result_json = {"extraction": result.normalized_input.model_dump(mode="json"), "cargo_recalculation": result.cargo_calculation.model_dump(mode="json"), "quote_result": result.model_dump(mode="json"), "customer_reply": result.customer_reply, "missing_fields": [], "manual_review_required": result.manual_review_required}
    record.snapshot_json = snapshot
    record.customer_reply = result.customer_reply
    if task is not None:
        task.status = "pending"
        task.result_json = snapshot
    transition(db, record, actor, "pending_review", "sales_submitted_additional_info", public_note="销售已补充资料并重新提交", metadata={"revision": record.revision})
    db.commit()
    return public_record(db, record)


@router.patch("/sales-records/{record_id}/manual-price")
def update_sales_quote_manual_price(
    record_id: int,
    payload: ManualPriceOverrideRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*MANUAL_TASK_WRITE_ROLES)),
) -> dict[str, object]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Manual price override requires second confirmation.")
    repository = SalesQuoteRecordRepository(db)
    record = repository.get_record(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sales quote record not found.")
    updated = repository.apply_manual_price(
        record=record,
        actor=actor,
        total_price_usd=payload.total_price_usd,
        override_note=payload.override_note.strip(),
        customer_reply=payload.customer_reply.strip() if payload.customer_reply and payload.customer_reply.strip() else None,
    )
    return sales_quote_record_to_dict(updated)


@router.patch("/sales-records/by-quote/{quote_id}/manual-price")
def update_sales_quote_manual_price_by_quote_id(
    quote_id: str,
    payload: ManualPriceOverrideRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*MANUAL_TASK_WRITE_ROLES)),
) -> dict[str, object]:
    if not payload.confirmed:
        raise HTTPException(status_code=400, detail="Manual price override requires second confirmation.")
    repository = SalesQuoteRecordRepository(db)
    record = repository.get_latest_record_by_quote_id(quote_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Sales quote record not found for this quote_id.")
    updated = repository.apply_manual_price(
        record=record,
        actor=actor,
        total_price_usd=payload.total_price_usd,
        override_note=payload.override_note.strip(),
        customer_reply=payload.customer_reply.strip() if payload.customer_reply and payload.customer_reply.strip() else None,
    )
    return sales_quote_record_to_dict(updated)
