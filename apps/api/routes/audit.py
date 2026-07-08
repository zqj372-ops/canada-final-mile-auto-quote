from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import AUDIT_READ_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.audit_service import (
    get_quote_audit as get_quote_audit_service,
    get_quote_error_summary as get_quote_error_summary_service,
    list_quote_audits as list_quote_audits_service,
)


router = APIRouter(prefix="/quotes", tags=["audit"])


@router.get("/audits", dependencies=[Depends(require_roles(*AUDIT_READ_ROLES))])
def list_quote_audits(
    db: Session = Depends(get_db),
    limit: int = 30,
    query: str | None = None,
) -> list[dict[str, object]]:
    return list_quote_audits_service(db, limit=limit, query=query)


@router.get("/audit/{quote_id}", dependencies=[Depends(require_roles(*AUDIT_READ_ROLES))])
def get_quote_audit(quote_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    return get_quote_audit_service(db, quote_id)


@router.get("/error-summary", dependencies=[Depends(require_roles(*AUDIT_READ_ROLES))])
def get_quote_error_summary(db: Session = Depends(get_db), limit: int = 20) -> dict[str, object]:
    return get_quote_error_summary_service(db, limit=limit)
