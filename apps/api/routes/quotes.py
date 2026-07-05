from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from apps.api.auth import QUOTE_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.quote_service import calculate_vendor_quote, calculate_zone_quote as calculate_zone_quote_service
from packages.quote_engine.models import QuoteResult, ShipmentInput
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])


class ZoneQuoteWithNotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: ZoneQuoteRequest
    notify_wecom: bool = False
    wecom_bot_id: int | None = None


@router.post("/calculate", response_model=QuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_quote(shipment: ShipmentInput, db: Session = Depends(get_db)) -> QuoteResult:
    return calculate_vendor_quote(db, shipment)


@router.post("/zone-calculate", response_model=ZoneQuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_zone_quote(
    payload: ZoneQuoteWithNotifyRequest | ZoneQuoteRequest,
    db: Session = Depends(get_db),
) -> ZoneQuoteResult:
    quote_payload, notify_wecom, wecom_bot_id = _normalize_zone_payload(payload)
    return calculate_zone_quote_service(
        db,
        quote_payload,
        notify_wecom=notify_wecom,
        wecom_bot_id=wecom_bot_id,
    )


def _normalize_zone_payload(
    payload: ZoneQuoteWithNotifyRequest | ZoneQuoteRequest,
) -> tuple[ZoneQuoteRequest, bool, int | None]:
    if isinstance(payload, ZoneQuoteWithNotifyRequest):
        return payload.quote, payload.notify_wecom, payload.wecom_bot_id
    return payload, False, None
