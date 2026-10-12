from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.repositories.hermes_learning_candidate_repository import (
    HermesLearningCandidateRepository,
    LearningReviewConflict,
    hermes_candidate_to_dict,
)
from apps.api.db.repositories.learned_quote_rule_repository import learned_quote_rule_to_dict


class HermesCandidateReviewPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    review_note: str | None = None
    supplier: str | None = Field(default=None, min_length=1, max_length=200)
    source_reference: str | None = Field(default=None, min_length=1, max_length=1000)
    valid_from: datetime | None = None
    valid_until: datetime | None = None
    expected_evidence_version: str | None = None


class LearnedRuleUpdatePayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    status: str
    note: str | None = None


def list_hermes_candidates(
    db: Session,
    *,
    status: str | None = None,
    postal_prefix: str | None = None,
    city: str | None = None,
    province: str | None = None,
    billing_pallets: int | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    records = HermesLearningCandidateRepository(db).list_candidates(
        status=status,
        postal_prefix=postal_prefix,
        city=city,
        province=province,
        billing_pallets=billing_pallets,
        limit=limit,
    )
    return [hermes_candidate_to_dict(record) for record in records]


def get_hermes_candidate(db: Session, candidate_id: int) -> dict[str, object]:
    record = HermesLearningCandidateRepository(db).get(candidate_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Hermes learning candidate not found.")
    return hermes_candidate_to_dict(record)


def approve_hermes_candidate(
    db: Session,
    candidate_id: int,
    payload: HermesCandidateReviewPayload,
    actor: CurrentActor,
) -> dict[str, object]:
    terms = {
        "supplier": payload.supplier, "source_reference": payload.source_reference,
        "valid_from": (payload.valid_from or datetime.now(timezone.utc)).isoformat(),
        "valid_until": payload.valid_until.isoformat() if payload.valid_until else None,
        "currency": "USD", "price_type": "all_in",
    }
    try:
        approved = HermesLearningCandidateRepository(db).approve(
            candidate_id, reviewed_by=actor.name, review_note=payload.review_note,
            price_terms=terms, expected_evidence_version=payload.expected_evidence_version,
        )
    except LearningReviewConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if approved is None:
        raise HTTPException(status_code=404, detail="Hermes learning candidate not found.")
    candidate, rule = approved
    return {
        "candidate": hermes_candidate_to_dict(candidate),
        "learned_rule": learned_quote_rule_to_dict(rule),
    }


def reject_hermes_candidate(
    db: Session,
    candidate_id: int,
    payload: HermesCandidateReviewPayload,
    actor: CurrentActor,
) -> dict[str, object]:
    try:
        rejected = HermesLearningCandidateRepository(db).reject(
            candidate_id, reviewed_by=actor.name, review_note=payload.review_note,
        )
    except LearningReviewConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if rejected is None:
        raise HTTPException(status_code=404, detail="Hermes learning candidate not found.")
    return hermes_candidate_to_dict(rejected)


def update_learned_rule(
    db: Session,
    rule_id: int,
    payload: LearnedRuleUpdatePayload,
) -> dict[str, object]:
    if payload.status not in {"active", "disabled", "inactive", "rejected"}:
        raise HTTPException(status_code=422, detail="status must be active, disabled, inactive, or rejected.")
    try:
        rule = HermesLearningCandidateRepository(db).update_learned_rule_status(
            rule_id, status=payload.status, note=payload.note,
        )
    except LearningReviewConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if rule is None:
        raise HTTPException(status_code=404, detail="Learned quote rule not found.")
    return learned_quote_rule_to_dict(rule)
