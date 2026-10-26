from fastapi import APIRouter, Depends

from apps.api.auth import AI_QUOTE_WRITE_ROLES, CurrentActor, require_roles
from apps.api.services.quote_admission import reserve_api_quote
from apps.api.services.sailing_schedule import ScheduleInput, ScheduleResponse, query_schedules

router = APIRouter(prefix='/schedules', tags=['public-schedules'])


@router.post('/query', response_model=ScheduleResponse)
def schedule_query(payload: ScheduleInput,
                   actor: CurrentActor = Depends(require_roles(*AI_QUOTE_WRITE_ROLES))):
    reserve_api_quote(actor)
    return query_schedules(payload)
