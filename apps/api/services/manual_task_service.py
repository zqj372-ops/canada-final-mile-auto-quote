from decimal import Decimal
import logging

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask
from apps.api.db.repositories.hermes_learning_candidate_repository import HermesLearningCandidateRepository
from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
from apps.api.services.notification_service import notify_manual_task_resolved
from apps.api.services.quote_issue_labels import localize_issue_reason, risk_tag_labels
from apps.api.services.quote_service import try_wecom_notify


logger = logging.getLogger(__name__)


class ManualQuoteTaskUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: str | None = Field(default=None, min_length=1)
    assigned_to: str | None = None
    resolved_price_usd: Decimal | None = Field(default=None, ge=0)
    resolved_note: str | None = None
    notify_wecom: bool = False
    wecom_bot_id: int | None = None


def list_manual_quote_tasks(db: Session) -> list[dict[str, object]]:
    return [manual_task_to_dict(task) for task in ManualQuoteTaskRepository(db).list_tasks()]


def update_manual_quote_task(
    db: Session,
    task_id: int,
    payload: ManualQuoteTaskUpdate,
) -> dict[str, object]:
    update = payload.model_dump(exclude_unset=True)
    notify_wecom = bool(update.pop("notify_wecom", False))
    wecom_bot_id = update.pop("wecom_bot_id", None)
    task = ManualQuoteTaskRepository(db).update(task_id, **update)
    if task is None:
        raise HTTPException(status_code=404, detail="Manual quote task not found.")
    if task.status == "resolved" and task.resolved_price_usd is not None:
        try:
            HermesLearningCandidateRepository(db).create_from_manual_task(task)
        except Exception:
            logger.exception("Failed to create Hermes learning candidate from resolved manual quote task.", extra={"task_id": task.id})
            db.rollback()
    if notify_wecom and payload.status == "resolved":
        try_wecom_notify(
            "manual_resolved",
            lambda: notify_manual_task_resolved(db, task=task, bot_id=wecom_bot_id),
            task.quote_id,
        )
    return manual_task_to_dict(task)


def manual_task_to_dict(record: ManualQuoteTask) -> dict[str, object]:
    return {
        "id": record.id,
        "quote_id": record.quote_id,
        "reason": record.reason,
        "reason_zh": localize_issue_reason(record.reason),
        "risk_tags": record.risk_tags,
        "risk_tag_labels": risk_tag_labels(record.risk_tags),
        "request_json": record.request_json,
        "result_json": record.result_json,
        "status": record.status,
        "assigned_to": record.assigned_to,
        "resolved_price_usd": _decimal_to_string(record.resolved_price_usd),
        "resolved_note": record.resolved_note,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"
