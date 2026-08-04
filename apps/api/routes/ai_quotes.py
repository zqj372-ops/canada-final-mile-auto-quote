from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import AI_QUOTE_WRITE_ROLES, CurrentActor, require_roles
from apps.api.db.session import get_db
from apps.api.services.ai_quote_service import AIAutoQuoteRequest, AIAutoQuoteResponse, calculate_ai_auto_quote
from packages.quote_engine.zone_models import ZoneQuoteResult, to_public_zone_quote_result


router = APIRouter(prefix="/quotes", tags=["ai-quotes"])


@router.post(
    "/ai-auto-quote",
    response_model=AIAutoQuoteResponse,
)
def calculate_ai_auto_quote_route(
    payload: AIAutoQuoteRequest,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES)),
) -> AIAutoQuoteResponse:
    response = calculate_ai_auto_quote(db, payload, actor=actor)
    # Keep this API boundary defensive even if an internal caller or a legacy
    # plugin still returns a full ZoneQuoteResult.  The service normally
    # provides the allowlisted DTO already; this conversion is a no-op for
    # the public result and prevents internal trace fields from escaping.
    if isinstance(response.quote_result, ZoneQuoteResult):
        response = response.model_copy(
            update={"quote_result": to_public_zone_quote_result(response.quote_result)}
        )
    return response
