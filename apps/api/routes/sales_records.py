from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from apps.api.auth import ALL_ROLES, CurrentActor, require_roles
from apps.api.db.repositories.sales_quote_record_repository import (
    SalesQuoteRecordRepository,
    sales_quote_record_to_dict,
)
from apps.api.db.session import get_db


router = APIRouter(prefix="/quotes", tags=["sales-records"])


@router.get("/sales-records")
def list_sales_quote_records(
    status: str | None = Query(default=None, pattern="^(quoted|manual_required)$"),
    limit: int = 50,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*ALL_ROLES)),
) -> list[dict[str, object]]:
    records = SalesQuoteRecordRepository(db).list_records(actor=actor, status=status, limit=limit)
    return [sales_quote_record_to_dict(record) for record in records]
