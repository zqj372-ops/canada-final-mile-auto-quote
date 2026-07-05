from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from apps.api.db.models import QuoteAuditLog
from apps.api.db.repositories.quote_audit_repository import QuoteAuditRepository


def get_quote_audit(db: Session, quote_id: str) -> dict[str, object]:
    record = QuoteAuditRepository(db).get_by_quote_id(quote_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quote audit log not found.")
    return audit_to_dict(record)


def audit_to_dict(record: QuoteAuditLog) -> dict[str, object]:
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


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"
