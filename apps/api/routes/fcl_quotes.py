from fastapi import APIRouter, Depends, Header
from sqlalchemy.orm import Session

from apps.api.auth import AI_QUOTE_WRITE_ROLES, CurrentActor, require_roles
from apps.api.db.session import get_db
from apps.api.services.fcl_quote_service import (
    FCLAutoQuoteRequest,
    FCLAutoQuoteResponse,
    calculate_fcl_auto_quote,
)


router = APIRouter(prefix="/quotes", tags=["fcl-quotes"])


@router.post("/fcl-auto-quote", response_model=FCLAutoQuoteResponse)
def calculate_fcl_auto_quote_route(
    payload: FCLAutoQuoteRequest,
    idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=128),
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES)),
) -> FCLAutoQuoteResponse:
    return calculate_fcl_auto_quote(db, payload, actor=actor, idempotency_key=idempotency_key)
