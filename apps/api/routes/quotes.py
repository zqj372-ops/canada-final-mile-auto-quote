from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, model_validator
from sqlalchemy.orm import Session

from apps.api.auth import QUOTE_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.quote_service import calculate_vendor_quote, calculate_zone_quote as calculate_zone_quote_service
from packages.quote_engine.models import QuoteResult, ShipmentInput
from packages.quote_engine.zone_models import (
    ZoneQuotePublicResult,
    ZoneQuoteRequest,
)


router = APIRouter(prefix="/quotes", tags=["quotes"])


class ZoneQuoteWithNotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: ZoneQuoteRequest
    notify_email: bool = False
    email_config_id: int | None = None
    notify_wecom: bool = False
    wecom_bot_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def wrap_flat_quote(cls, value: object) -> object:
        if isinstance(value, dict) and "quote" not in value:
            return {"quote": value}
        return value


@router.post("/calculate", response_model=QuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_quote(shipment: ShipmentInput, db: Session = Depends(get_db)) -> QuoteResult:
    return calculate_vendor_quote(db, shipment)


@router.post(
    "/zone-calculate",
    response_model=ZoneQuotePublicResult,
    dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))],
)
def calculate_zone_quote(
    payload: ZoneQuoteWithNotifyRequest,
    db: Session = Depends(get_db),
) -> ZoneQuotePublicResult:
    result = calculate_zone_quote_service(
        db,
        payload.quote,
        notify_email=payload.notify_email,
        email_config_id=payload.email_config_id,
        notify_wecom=payload.notify_wecom,
        wecom_bot_id=payload.wecom_bot_id,
    )
    return result.to_public()
