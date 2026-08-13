from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import QUOTE_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.source_status_service import SourceStatus, get_source_status


router = APIRouter(prefix="/api", tags=["system"])


@router.get(
    "/status",
    response_model=SourceStatus,
    dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES, update_api_key_last_used=False))],
)
def source_status(db: Session = Depends(get_db)) -> SourceStatus:
    return get_source_status(db)
