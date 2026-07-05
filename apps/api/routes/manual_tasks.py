from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import MANUAL_TASK_READ_ROLES, MANUAL_TASK_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.manual_task_service import (
    ManualQuoteTaskUpdate,
    list_manual_quote_tasks as list_manual_quote_tasks_service,
    update_manual_quote_task as update_manual_quote_task_service,
)


router = APIRouter(prefix="/quotes", tags=["manual-tasks"])


@router.get("/manual-tasks", dependencies=[Depends(require_roles(*MANUAL_TASK_READ_ROLES))])
def list_manual_quote_tasks(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return list_manual_quote_tasks_service(db)


@router.patch("/manual-tasks/{task_id}", dependencies=[Depends(require_roles(*MANUAL_TASK_WRITE_ROLES))])
def update_manual_quote_task(
    task_id: int,
    payload: ManualQuoteTaskUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return update_manual_quote_task_service(db, task_id, payload)
