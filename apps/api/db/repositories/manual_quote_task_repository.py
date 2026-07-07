from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


class ManualQuoteTaskRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_from_zone_quote(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> ManualQuoteTask:
        record = ManualQuoteTask(
            quote_id=result.quote_id,
            reason=result.matched_rule,
            risk_tags=result.risk_tags,
            request_json=request.model_dump(mode="json"),
            result_json=result.model_dump(mode="json"),
            status="pending",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def create_ai_review_task(
        self,
        *,
        quote_id: str,
        reason: str,
        risk_tags: list[str],
        request_json: dict[str, Any],
        result_json: dict[str, Any],
    ) -> ManualQuoteTask:
        record = ManualQuoteTask(
            quote_id=quote_id,
            reason=reason,
            risk_tags=risk_tags,
            request_json=request_json,
            result_json=result_json,
            status="pending",
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_tasks(self) -> list[ManualQuoteTask]:
        return list(
            self.session.scalars(select(ManualQuoteTask).order_by(ManualQuoteTask.created_at.desc(), ManualQuoteTask.id.desc()))
        )

    def get(self, task_id: int) -> ManualQuoteTask | None:
        return self.session.get(ManualQuoteTask, task_id)

    def update(
        self,
        task_id: int,
        *,
        status: str | None = None,
        assigned_to: str | None = None,
        resolved_price_usd: Decimal | None = None,
        resolved_note: str | None = None,
    ) -> ManualQuoteTask | None:
        record = self.get(task_id)
        if record is None:
            return None
        if status is not None:
            record.status = status
        if assigned_to is not None:
            record.assigned_to = assigned_to
        if resolved_price_usd is not None:
            record.resolved_price_usd = resolved_price_usd
        if resolved_note is not None:
            record.resolved_note = resolved_note
        self.session.commit()
        self.session.refresh(record)
        return record
