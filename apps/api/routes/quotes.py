from decimal import Decimal
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask, QuoteAuditLog
from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
from apps.api.db.repositories.quote_audit_repository import QuoteAuditRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.rate_rule_repository import RateRuleRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.db.session import get_db
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
