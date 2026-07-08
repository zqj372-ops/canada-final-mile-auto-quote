from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.auth import ALL_ROLES, MANUAL_TASK_WRITE_ROLES, CurrentActor, require_roles
from apps.api.db.repositories.sales_quote_record_repository import (
    SalesQuoteRecordRepository,
    sales_quote_record_to_dict,
)
from apps.api.db.session import get_db


router = APIRouter(prefix="/quotes", tags=["sales-records"])


class ManualPriceOverrideRequest(BaseModel):
    total_price_usd: Decimal = Field(ge=0)
    override_note: str = Field(min_length=2, max_length=1000)
    customer_reply: str | None = Field(default=None, max_length=5000)
    confirmed: bool = False


@router.get("/sales-records")
def list_sales_quote_records(
    status: str | None = Query(default=None, pattern="^(quoted|manual_required)$"),
    limit: int = 50,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*ALL_ROLES)),
) -> list[dict[str, object]]:
    records = SalesQuoteRecordRepository(db).list_records(actor=actor, status=status, limit=limit)
    return [sales_quote_record_to_dict(record) for record in records]


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
