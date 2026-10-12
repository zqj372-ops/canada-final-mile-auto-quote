from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import AI_QUOTE_WRITE_ROLES, QUOTE_WRITE_ROLES, CurrentActor, require_roles
from apps.api.db.session import get_db
from apps.api.services.ai_quote_service import AIAutoQuoteRequest, AIAutoQuoteResponse, calculate_ai_auto_quote
from apps.api.services.quote_workbench_service import (
    AIExtractRequest, AIExtractResponse, ConfirmedCalculateRequest, ConfirmedCalculateResponse,
    extract_for_workbench, calculate_confirmed,
)


router = APIRouter(prefix="/quotes", tags=["ai-quotes"])


@router.post("/ai-extract", response_model=AIExtractResponse)
def extract_quote_route(
    payload: AIExtractRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES)),
) -> AIExtractResponse:
    return extract_for_workbench(db, payload, actor)


@router.post("/confirmed-calculate", response_model=ConfirmedCalculateResponse)
def calculate_confirmed_route(
    payload: ConfirmedCalculateRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*QUOTE_WRITE_ROLES)),
) -> ConfirmedCalculateResponse:
    return calculate_confirmed(db, payload, actor)


@router.post(
    "/ai-auto-quote",
    response_model=AIAutoQuoteResponse,
)
def calculate_ai_auto_quote_route(
    payload: AIAutoQuoteRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES)),
) -> AIAutoQuoteResponse:
    return calculate_ai_auto_quote(db, payload, actor=actor)
