from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import ManualQuoteTask, QuoteWorkflowEvent, SalesQuoteRecord
from apps.api.db.repositories.sales_quote_record_repository import sales_quote_record_to_dict
from packages.quote_engine.fcl import FCLQuoteDraft

WORKFLOW_LABELS = {
    "pending_review": "待后台处理", "in_review": "后台处理中", "needs_sales_info": "待销售补资料",
    "ready_to_send": "待销售发送", "sent": "已发送，待客户回复", "accepted": "客户已接受",
    "rejected": "客户未接受", "expired": "已过期", "cancelled": "已取消",
}
NEXT_ACTIONS = {
    "pending_review": "后台领取处理", "in_review": "后台确认报价或要求补资料", "needs_sales_info": "补充资料并重新提交",
    "ready_to_send": "复制客户回复并发送", "sent": "登记客户结果", "accepted": "已完成", "rejected": "已完成",
    "expired": "复制为新报价", "cancelled": "已取消",
}
ALLOWED_ACTIONS = {
    "ready_to_send": ["copy_customer_reply", "print_pdf", "mark_sent", "cancel", "copy_new_quote"],
    "sent": ["record_outcome", "mark_expired", "cancel"],
    "needs_sales_info": ["submit_additional_info", "cancel"],
    "accepted": ["copy_new_quote"], "rejected": ["copy_new_quote"], "expired": ["copy_new_quote"], "cancelled": ["copy_new_quote"],
    "pending_review": [], "in_review": [],
}


class MarkSentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channel: str = Field(min_length=1, max_length=32)
    note: str | None = Field(default=None, max_length=1000)


class OutcomeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    outcome: str = Field(pattern="^(accepted|rejected|expired|cancelled)$")
    note: str | None = Field(default=None, max_length=1000)


class AdditionalInfoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed_fields: FCLQuoteDraft


class ManualResolution(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fee_items: list[dict[str, Any]] = Field(min_length=1)
    totals_by_currency: dict[str, Decimal] = Field(min_length=1)
    settlement_currency: str | None = Field(default=None, min_length=3, max_length=8)
    converted_total: Decimal | None = Field(default=None, ge=0)
    valid_until: date
    public_note: str = Field(min_length=1, max_length=2000)
    customer_terms: list[str] = Field(default_factory=list)
    customer_reply: str = Field(min_length=1, max_length=10000)
    internal_note: str | None = Field(default=None, max_length=5000)


def assert_sales_owner(record: SalesQuoteRecord, actor: CurrentActor) -> None:
    if actor.role == "sales" and actor.user_id is not None and record.actor_user_id != actor.user_id:
        raise HTTPException(status_code=403, detail="Sales users may only operate their own quotes.")


def record_event(db: Session, record: SalesQuoteRecord, actor: CurrentActor, event_type: str, *, to_status: str | None = None, public_note: str | None = None, internal_note: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    db.add(QuoteWorkflowEvent(record_id=record.id, event_type=event_type, from_status=record.workflow_status, to_status=to_status, actor_id=actor.user_id, actor_name=actor.name, actor_role=actor.role, public_note=public_note, internal_note=internal_note, metadata_json=metadata or {}))


def transition(db: Session, record: SalesQuoteRecord, actor: CurrentActor, to_status: str, event_type: str, *, public_note: str | None = None, internal_note: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    allowed = {
        "ready_to_send": {"sent", "cancelled"}, "sent": {"accepted", "rejected", "expired", "cancelled"},
        "needs_sales_info": {"pending_review", "cancelled"}, "pending_review": {"in_review"},
        "in_review": {"needs_sales_info", "ready_to_send", "cancelled"},
    }
    if to_status not in allowed.get(record.workflow_status, set()):
        raise HTTPException(status_code=409, detail=f"非法状态转换：{record.workflow_status} -> {to_status}")
    previous = record.workflow_status
    record.workflow_status = to_status
    record.status = "quoted" if to_status in {"ready_to_send", "sent", "accepted", "rejected", "expired"} else ("manual_required" if to_status in {"pending_review", "in_review", "needs_sales_info"} else "cancelled")
    record.last_action_by = actor.name
    record.last_action_role = actor.role
    if to_status in {"accepted", "rejected", "expired", "cancelled"}:
        record.closed_at = datetime.now(UTC)
    record_event(db, record, actor, event_type, to_status=to_status, public_note=public_note, internal_note=internal_note, metadata=metadata)
    db.flush()
    assert previous != record.workflow_status


def timeline(db: Session, record_id: int) -> list[dict[str, Any]]:
    rows = db.scalars(select(QuoteWorkflowEvent).where(QuoteWorkflowEvent.record_id == record_id).order_by(QuoteWorkflowEvent.created_at, QuoteWorkflowEvent.id)).all()
    return [{"event_type": row.event_type, "from_status": row.from_status, "to_status": row.to_status, "actor_name": row.actor_name, "actor_role": row.actor_role, "public_note": row.public_note, "created_at": row.created_at.isoformat() if row.created_at else None} for row in rows]


def public_record(db: Session, record: SalesQuoteRecord) -> dict[str, Any]:
    payload = sales_quote_record_to_dict(record)
    payload.pop("request_json", None)
    payload.pop("result_json", None)
    payload["workflow_status"] = record.workflow_status
    payload["status_label"] = WORKFLOW_LABELS.get(record.workflow_status, record.workflow_status)
    payload["next_action"] = NEXT_ACTIONS.get(record.workflow_status, "")
    payload["allowed_actions"] = ALLOWED_ACTIONS.get(record.workflow_status, [])
    payload["valid_until"] = record.valid_until.isoformat() if record.valid_until else None
    payload["sent_at"] = record.sent_at.isoformat() if record.sent_at else None
    payload["public_snapshot"] = _public_snapshot(record)
    payload["timeline"] = timeline(db, record.id)
    return payload


def _public_snapshot(record: SalesQuoteRecord) -> dict[str, Any]:
    result = dict(record.snapshot_json or {})
    for key in ("internal_note", "source", "priority", "rate_card_id", "vendor", "cost_unit_price", "raw_message", "request", "config", "matched_rate_cards", "exchange_snapshot"):
        result.pop(key, None)
    quote_result = result.get("quote_result")
    if isinstance(quote_result, dict):
        quote_result = dict(quote_result)
        quote_result.pop("matched_rate_cards", None)
        quote_result["fee_items"] = [_public_fee_item(item) for item in quote_result.get("fee_items", []) if isinstance(item, dict)]
        result["quote_result"] = quote_result
    result["fee_items"] = [_public_fee_item(item) for item in result.get("fee_items", []) if isinstance(item, dict)]
    return result


def _public_fee_item(item: dict[str, Any]) -> dict[str, Any]:
    allowed = ("item_name", "description", "quantity", "unit", "unit_price", "amount", "currency", "pricing_status", "display_mode", "included", "public_note", "container_type")
    return {key: item[key] for key in allowed if key in item}
