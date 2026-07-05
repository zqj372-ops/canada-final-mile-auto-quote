from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.db.session import get_db
from apps.api.services.ai_quote_service import AIAutoQuoteRequest, AIAutoQuoteResponse, calculate_ai_auto_quote


router = APIRouter(prefix="/quotes", tags=["ai-quotes"])


@router.post("/ai-auto-quote", response_model=AIAutoQuoteResponse)
def calculate_ai_auto_quote_route(
    payload: AIAutoQuoteRequest,
    db: Session = Depends(get_db),
) -> AIAutoQuoteResponse:
    return calculate_ai_auto_quote(db, payload)
