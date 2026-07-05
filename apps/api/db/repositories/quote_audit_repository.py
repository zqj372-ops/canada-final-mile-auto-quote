from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import QuoteAuditLog
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


class QuoteAuditRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_for_zone_quote(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> QuoteAuditLog:
        record = QuoteAuditLog(
            quote_id=result.quote_id,
            request_json=request.model_dump(mode="json"),
            result_json=result.model_dump(mode="json"),
            source_type=result.source_type.value,
            postal_code=result.postal_code,
            postal_prefix=result.postal_prefix,
            city=result.city,
            province=result.province,
            origin=result.origin,
            zone=result.zone,
            billing_pallets=result.billing_pallets,
            base_price_usd=result.base_price_usd,
            total_price_usd=result.total_price_usd,
            manual_review_required=result.manual_review_required,
            risk_tags=result.risk_tags,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_by_quote_id(self, quote_id: str) -> QuoteAuditLog | None:
        return self.session.scalars(
            select(QuoteAuditLog).where(QuoteAuditLog.quote_id == quote_id).order_by(QuoteAuditLog.id.desc())
        ).first()
