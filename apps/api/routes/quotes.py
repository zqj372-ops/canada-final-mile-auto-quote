from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.db.repositories.rate_rule_repository import RateRuleRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.db.session import get_db
from packages.quote_engine.engine import QuoteEngine
from packages.quote_engine.models import QuoteCalculationRequest, QuoteResult, ShipmentInput
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.post("/calculate", response_model=QuoteResult)
def calculate_quote(shipment: ShipmentInput, db: Session = Depends(get_db)) -> QuoteResult:
    candidate_rules = RateRuleRepository(db).list_candidate_rules(shipment)
    request = QuoteCalculationRequest(shipment=shipment, rate_rules=candidate_rules)
    return QuoteEngine().quote(request)


@router.post("/zone-calculate", response_model=ZoneQuoteResult)
def calculate_zone_quote(payload: ZoneQuoteRequest, db: Session = Depends(get_db)) -> ZoneQuoteResult:
    return ZoneQuoteEngine(ZoneRepository(db)).quote(payload)
