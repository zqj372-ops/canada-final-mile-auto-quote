from fastapi import APIRouter

from packages.quote_engine.engine import QuoteEngine
from packages.quote_engine.models import QuoteCalculationRequest, QuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])


@router.post("", response_model=QuoteResult)
def create_quote(payload: QuoteCalculationRequest) -> QuoteResult:
    return QuoteEngine().quote(payload)

