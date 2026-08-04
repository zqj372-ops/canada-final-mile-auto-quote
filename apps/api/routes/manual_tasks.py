from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from apps.api.auth import MANUAL_TASK_READ_ROLES, MANUAL_TASK_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.manual_task_service import (
    ManualQuoteTaskUpdate,
    list_manual_quote_tasks as list_manual_quote_tasks_service,
    update_manual_quote_task as update_manual_quote_task_service,
)
from apps.api.auth import CurrentActor
from apps.api.db.models import ManualQuoteTask, SalesQuoteRecord
from apps.api.services.quote_workflow_service import ManualResolution, assert_sales_owner, public_record, transition
from sqlalchemy import select


router = APIRouter(prefix="/quotes", tags=["manual-tasks"])


@router.get("/manual-tasks", dependencies=[Depends(require_roles(*MANUAL_TASK_READ_ROLES))])
def list_manual_quote_tasks(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return list_manual_quote_tasks_service(db)


@router.patch("/manual-tasks/{task_id}", dependencies=[Depends(require_roles(*MANUAL_TASK_WRITE_ROLES))])
def update_manual_quote_task(
    task_id: int,
    payload: ManualQuoteTaskUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return update_manual_quote_task_service(db, task_id, payload)


def _get_task(db: Session, task_id: int) -> tuple[ManualQuoteTask, SalesQuoteRecord]:
    task = db.get(ManualQuoteTask, task_id)
    if task is None or task.sales_quote_record_id is None:
        raise HTTPException(status_code=404, detail="Manual quote task not found.")
    record = db.get(SalesQuoteRecord, task.sales_quote_record_id)
    if record is None:
        raise HTTPException(status_code=409, detail="Manual task is not linked to a sales quote record.")
    return task, record


@router.post("/manual-tasks/{task_id}/claim")
def claim_manual_task(task_id: int, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*MANUAL_TASK_WRITE_ROLES))) -> dict[str, object]:
    task, record = _get_task(db, task_id)
    if record.workflow_status != "pending_review" or task.status not in {"pending", "in_progress"}:
        raise HTTPException(status_code=409, detail="任务当前不可领取。")
    task.status = "in_progress"
    task.assigned_to = actor.name
    transition(db, record, actor, "in_review", "manual_task_claimed", public_note="后台已领取处理")
    db.commit()
    return {**record_public_task(task), "sales_quote_record": public_record(db, record)}


@router.post("/manual-tasks/{task_id}/resolve")
def resolve_manual_task(task_id: int, payload: ManualResolution, db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*MANUAL_TASK_WRITE_ROLES))) -> dict[str, object]:
    task, record = _get_task(db, task_id)
    if record.workflow_status != "in_review" or task.status != "in_progress":
        raise HTTPException(status_code=409, detail="任务当前不可确认。")
    task.status = "resolved"
    task.fee_items = payload.fee_items
    task.totals_by_currency = {key: f"{value:.2f}" for key, value in payload.totals_by_currency.items()}
    task.settlement_currency = payload.settlement_currency
    task.converted_total = payload.converted_total
    task.valid_until = payload.valid_until
    task.public_note = payload.public_note
    task.customer_terms = payload.customer_terms
    task.customer_reply = payload.customer_reply
    task.internal_note = payload.internal_note
    snapshot = dict(record.snapshot_json or {})
    snapshot.update({"fee_items": payload.fee_items, "totals_by_currency": task.totals_by_currency, "settlement_currency": payload.settlement_currency, "converted_total": str(payload.converted_total) if payload.converted_total is not None else None, "quote_valid_until": payload.valid_until.isoformat(), "public_note": payload.public_note, "customer_terms": payload.customer_terms, "customer_reply": payload.customer_reply})
    record.snapshot_json = snapshot
    record.customer_reply = payload.customer_reply
    record.valid_until = payload.valid_until
    record.result_json = {**(record.result_json or {}), "customer_reply": payload.customer_reply, "quote_result": {**((record.result_json or {}).get("quote_result") or {}), "fee_items": payload.fee_items, "totals_by_currency": task.totals_by_currency, "settlement_currency": payload.settlement_currency, "converted_total": str(payload.converted_total) if payload.converted_total is not None else None, "quote_valid_until": payload.valid_until.isoformat(), "public_terms": payload.customer_terms}}
    transition(db, record, actor, "ready_to_send", "manual_quote_confirmed", public_note=payload.public_note, internal_note=payload.internal_note)
    db.commit()
    return {**record_public_task(task), "sales_quote_record": public_record(db, record)}


@router.post("/manual-tasks/{task_id}/request-info")
def request_manual_task_info(task_id: int, payload: dict[str, str], db: Session = Depends(get_db), actor: CurrentActor = Depends(require_roles(*MANUAL_TASK_WRITE_ROLES))) -> dict[str, object]:
    note = (payload.get("public_note") or "").strip()
    if not note:
        raise HTTPException(status_code=422, detail="需要销售补充什么不能为空。")
    task, record = _get_task(db, task_id)
    task.status = "needs_sales_info"
    task.public_note = note
    transition(db, record, actor, "needs_sales_info", "manual_requested_sales_info", public_note=note)
    db.commit()
    return {**record_public_task(task), "sales_quote_record": public_record(db, record)}


def record_public_task(task: ManualQuoteTask) -> dict[str, object]:
    return {"id": task.id, "quote_id": task.quote_id, "sales_quote_record_id": task.sales_quote_record_id, "status": task.status, "assigned_to": task.assigned_to, "reason": task.reason, "reason_zh": task.reason, "public_note": task.public_note, "created_at": task.created_at.isoformat() if task.created_at else None, "updated_at": task.updated_at.isoformat() if task.updated_at else None}
