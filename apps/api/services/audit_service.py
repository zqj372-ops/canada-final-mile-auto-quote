from decimal import Decimal
from collections import Counter
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.db.models import HermesLearningCandidate, LearnedQuoteRule, ManualQuoteTask, QuoteAuditLog
from apps.api.db.repositories.hermes_learning_candidate_repository import hermes_candidate_to_dict
from apps.api.db.repositories.learned_quote_rule_repository import learned_quote_rule_to_dict
from apps.api.db.repositories.quote_audit_repository import QuoteAuditRepository
from apps.api.services.manual_task_service import manual_task_to_dict
from apps.api.services.quote_issue_labels import risk_tag_label, risk_tag_labels


def get_quote_audit(db: Session, quote_id: str) -> dict[str, object]:
    record = QuoteAuditRepository(db).get_by_quote_id(quote_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Quote audit log not found.")
    return audit_to_dict(record)


def get_quote_error_summary(db: Session, *, limit: int = 20) -> dict[str, object]:
    safe_limit = max(1, min(limit, 100))
    window_started_at = datetime.now(timezone.utc) - timedelta(hours=24)
    total_audits = db.scalar(select(func.count(QuoteAuditLog.id))) or 0
    manual_audits = db.scalar(
        select(func.count(QuoteAuditLog.id)).where(QuoteAuditLog.manual_review_required.is_(True))
    ) or 0
    success_audits = db.scalar(
        select(func.count(QuoteAuditLog.id)).where(QuoteAuditLog.manual_review_required.is_(False))
    ) or 0

    pending_tasks = db.scalar(
        select(func.count(ManualQuoteTask.id)).where(ManualQuoteTask.status == "pending")
    ) or 0
    resolved_tasks = db.scalar(
        select(func.count(ManualQuoteTask.id)).where(ManualQuoteTask.status == "resolved")
    ) or 0
    ai_issue_tasks = db.scalar(
        select(func.count(ManualQuoteTask.id)).where(ManualQuoteTask.quote_id.like("ai_%"))
    ) or 0
    active_learning_rules = db.scalar(
        select(func.count(LearnedQuoteRule.id)).where(LearnedQuoteRule.status == "active")
    ) or 0
    pending_learning_candidates = db.scalar(
        select(func.count(HermesLearningCandidate.id)).where(HermesLearningCandidate.status == "pending_review")
    ) or 0
    approved_learning_candidates = db.scalar(
        select(func.count(HermesLearningCandidate.id)).where(HermesLearningCandidate.status == "approved")
    ) or 0
    rejected_learning_candidates = db.scalar(
        select(func.count(HermesLearningCandidate.id)).where(HermesLearningCandidate.status == "rejected")
    ) or 0
    learning_rule_usage_count = int(db.scalar(select(func.coalesce(func.sum(LearnedQuoteRule.usage_count), 0))) or 0)
    daily_total_audits = db.scalar(
        select(func.count(QuoteAuditLog.id)).where(QuoteAuditLog.created_at >= window_started_at)
    ) or 0
    daily_manual_audits = db.scalar(
        select(func.count(QuoteAuditLog.id)).where(
            QuoteAuditLog.created_at >= window_started_at,
            QuoteAuditLog.manual_review_required.is_(True),
        )
    ) or 0
    daily_success_audits = db.scalar(
        select(func.count(QuoteAuditLog.id)).where(
            QuoteAuditLog.created_at >= window_started_at,
            QuoteAuditLog.manual_review_required.is_(False),
        )
    ) or 0
    daily_created_tasks = db.scalar(
        select(func.count(ManualQuoteTask.id)).where(ManualQuoteTask.created_at >= window_started_at)
    ) or 0
    daily_pending_tasks = db.scalar(
        select(func.count(ManualQuoteTask.id)).where(
            ManualQuoteTask.created_at >= window_started_at,
            ManualQuoteTask.status == "pending",
        )
    ) or 0
    daily_ai_issue_tasks = db.scalar(
        select(func.count(ManualQuoteTask.id)).where(
            ManualQuoteTask.created_at >= window_started_at,
            ManualQuoteTask.quote_id.like("ai_%"),
        )
    ) or 0

    recent_tasks = list(
        db.scalars(
            select(ManualQuoteTask)
            .order_by(ManualQuoteTask.created_at.desc(), ManualQuoteTask.id.desc())
            .limit(safe_limit)
        )
    )
    recent_audits = list(
        db.scalars(
            select(QuoteAuditLog)
            .order_by(QuoteAuditLog.created_at.desc(), QuoteAuditLog.id.desc())
            .limit(safe_limit)
        )
    )
    recent_manual_audits = list(
        db.scalars(
            select(QuoteAuditLog)
            .where(QuoteAuditLog.manual_review_required.is_(True))
            .order_by(QuoteAuditLog.created_at.desc(), QuoteAuditLog.id.desc())
            .limit(safe_limit)
        )
    )
    recent_learning_rules = list(
        db.scalars(
            select(LearnedQuoteRule)
            .order_by(LearnedQuoteRule.updated_at.desc(), LearnedQuoteRule.id.desc())
            .limit(safe_limit)
        )
    )
    recent_learning_candidates = list(
        db.scalars(
            select(HermesLearningCandidate)
            .order_by(HermesLearningCandidate.updated_at.desc(), HermesLearningCandidate.id.desc())
            .limit(safe_limit)
        )
    )
    risk_counter: Counter[str] = Counter()
    for task in recent_tasks:
        risk_counter.update(task.risk_tags or [])
    daily_risk_counter: Counter[str] = Counter()
    for task in db.scalars(
        select(ManualQuoteTask)
        .where(ManualQuoteTask.created_at >= window_started_at)
        .order_by(ManualQuoteTask.created_at.desc(), ManualQuoteTask.id.desc())
        .limit(200)
    ):
        daily_risk_counter.update(task.risk_tags or [])

    return {
        "window_label": "近24小时",
        "window_started_at": window_started_at.isoformat(),
        "daily_total_audit_count": daily_total_audits,
        "daily_successful_quote_count": daily_success_audits,
        "daily_manual_required_audit_count": daily_manual_audits,
        "daily_created_manual_task_count": daily_created_tasks,
        "daily_pending_manual_task_count": daily_pending_tasks,
        "daily_ai_issue_task_count": daily_ai_issue_tasks,
        "daily_risk_tag_counts": _risk_counts(daily_risk_counter),
        "total_audit_count": total_audits,
        "successful_quote_count": success_audits,
        "manual_required_audit_count": manual_audits,
        "pending_manual_task_count": pending_tasks,
        "resolved_manual_task_count": resolved_tasks,
        "ai_issue_task_count": ai_issue_tasks,
        "active_learning_rule_count": active_learning_rules,
        "pending_learning_candidate_count": pending_learning_candidates,
        "approved_learning_candidate_count": approved_learning_candidates,
        "rejected_learning_candidate_count": rejected_learning_candidates,
        "learning_rule_usage_count": learning_rule_usage_count,
        "risk_tag_counts": _risk_counts(risk_counter),
        "recent_manual_tasks": [manual_task_to_dict(task) for task in recent_tasks],
        "recent_audits": [audit_to_dict(audit) for audit in recent_audits],
        "recent_manual_audits": [audit_to_dict(audit) for audit in recent_manual_audits],
        "recent_learning_rules": [learned_quote_rule_to_dict(rule) for rule in recent_learning_rules],
        "recent_learning_candidates": [hermes_candidate_to_dict(candidate) for candidate in recent_learning_candidates],
    }


def audit_to_dict(record: QuoteAuditLog) -> dict[str, object]:
    return {
        "id": record.id,
        "quote_id": record.quote_id,
        "request_json": record.request_json,
        "result_json": record.result_json,
        "source_type": record.source_type,
        "postal_code": record.postal_code,
        "postal_prefix": record.postal_prefix,
        "city": record.city,
        "province": record.province,
        "origin": record.origin,
        "zone": record.zone,
        "billing_pallets": record.billing_pallets,
        "base_price_usd": _decimal_to_string(record.base_price_usd),
        "total_price_usd": _decimal_to_string(record.total_price_usd),
        "manual_review_required": record.manual_review_required,
        "risk_tags": record.risk_tags,
        "risk_tag_labels": risk_tag_labels(record.risk_tags),
        "created_at": record.created_at.isoformat() if record.created_at else None,
    }


def _decimal_to_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value:.2f}"


def _risk_counts(counter: Counter[str]) -> list[dict[str, object]]:
    return [
        {"tag": tag, "label": risk_tag_label(tag), "count": count}
        for tag, count in counter.most_common(12)
    ]
