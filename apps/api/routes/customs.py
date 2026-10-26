from fastapi import APIRouter, Depends

from apps.api.auth import AI_QUOTE_WRITE_ROLES, CurrentActor, require_roles
from apps.api.services.quote_admission import reserve_api_quote
from apps.api.services.customs_reference import CustomsInput, CustomsResponse, input_blocked, query_customs
from apps.api.services.logistics_knowledge import KnowledgeInput, KnowledgeResponse, query_knowledge

router = APIRouter(prefix="/customs", tags=["customs-reference"])


@router.post("/reference-query", response_model=CustomsResponse)
def customs_reference_query(payload: CustomsInput,
                            actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES))):
    if not input_blocked(payload):
        reserve_api_quote(actor)
    return query_customs(payload)


@router.post("/knowledge-query", response_model=KnowledgeResponse)
def customs_knowledge_query(payload: KnowledgeInput,
                            actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES))):
    reserve_api_quote(actor)
    return query_knowledge(payload)
