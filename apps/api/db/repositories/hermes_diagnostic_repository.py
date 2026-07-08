from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import HermesDiagnosticQueue


class HermesDiagnosticRepository:
    def __init__(self, session: Session):
        self.session = session

    def create(
        self,
        *,
        quote_id: str,
        quote_status: str,
        source_type: str,
        diagnostic_package_json: dict[str, object],
    ) -> HermesDiagnosticQueue:
        record = HermesDiagnosticQueue(
            quote_id=quote_id,
            quote_status=quote_status,
            source_type=source_type,
            status="pending",
            diagnostic_package_json=diagnostic_package_json,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_records(
        self,
        *,
        status: str | None = None,
        quote_id: str | None = None,
        limit: int = 50,
    ) -> list[HermesDiagnosticQueue]:
        safe_limit = max(1, min(limit, 200))
        statement = select(HermesDiagnosticQueue)
        if status and status != "all":
            statement = statement.where(HermesDiagnosticQueue.status == status)
        if quote_id:
            statement = statement.where(HermesDiagnosticQueue.quote_id == quote_id)
        records = self.session.scalars(
            statement.order_by(HermesDiagnosticQueue.created_at.desc(), HermesDiagnosticQueue.id.desc()).limit(safe_limit)
        )
        return list(records)

    def get(self, diagnostic_id: int) -> HermesDiagnosticQueue | None:
        return self.session.get(HermesDiagnosticQueue, diagnostic_id)

    def get_by_quote_id(self, quote_id: str) -> HermesDiagnosticQueue | None:
        return self.session.scalars(
            select(HermesDiagnosticQueue)
            .where(HermesDiagnosticQueue.quote_id == quote_id)
            .order_by(HermesDiagnosticQueue.created_at.desc(), HermesDiagnosticQueue.id.desc())
        ).first()

    def save_suggestion(
        self,
        diagnostic_id: int,
        *,
        status: str,
        suggestion: dict[str, object] | None = None,
        agent_error: str | None = None,
        learning_candidate_id: int | None = None,
    ) -> HermesDiagnosticQueue | None:
        record = self.get(diagnostic_id)
        if record is None:
            return None
        record.status = status
        record.agent_suggestion_json = suggestion
        record.agent_error = agent_error
        record.learning_candidate_id = learning_candidate_id
        if suggestion:
            record.suggested_action = _string_value(suggestion.get("suggested_action") or suggestion.get("action"))
            record.confidence = _int_value(suggestion.get("confidence"))
            record.recommend_manual_review = _bool_value(suggestion.get("recommend_manual_review"))
            record.recommend_learning_candidate = _bool_value(suggestion.get("recommend_learning_candidate"))
        self.session.commit()
        self.session.refresh(record)
        return record


def hermes_diagnostic_to_dict(record: HermesDiagnosticQueue) -> dict[str, object]:
    return {
        "id": record.id,
        "quote_id": record.quote_id,
        "quote_status": record.quote_status,
        "source_type": record.source_type,
        "status": record.status,
        "diagnostic_package": record.diagnostic_package_json or {},
        "agent_suggestion": record.agent_suggestion_json,
        "agent_error": record.agent_error,
        "suggested_action": record.suggested_action,
        "confidence": record.confidence,
        "recommend_manual_review": record.recommend_manual_review,
        "recommend_learning_candidate": record.recommend_learning_candidate,
        "learning_candidate_id": record.learning_candidate_id,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _bool_value(value: object) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "是", "建议"}:
            return True
        if lowered in {"false", "0", "no", "n", "否", "不建议"}:
            return False
    return bool(value)
