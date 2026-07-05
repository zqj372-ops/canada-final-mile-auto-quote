from fastapi import APIRouter, Depends

from apps.api.auth import ALL_ROLES, BACKOFFICE_ROLES, CurrentActor, require_roles


router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/me", response_model=CurrentActor)
def get_current_actor(actor: CurrentActor = Depends(require_roles(*ALL_ROLES))) -> CurrentActor:
    return actor


@router.get("/backoffice", response_model=CurrentActor)
def get_backoffice_actor(actor: CurrentActor = Depends(require_roles(*BACKOFFICE_ROLES))) -> CurrentActor:
    return actor
