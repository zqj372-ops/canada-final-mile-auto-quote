from __future__ import annotations

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.repositories.hermes_learning_candidate_repository import (
    HermesLearningCandidateRepository,
    hermes_candidate_to_dict,
)
from apps.api.db.repositories.learned_quote_rule_repository import learned_quote_rule_to_dict


class HermesCandidateReviewPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    review_note: str | None = None


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
    try:
        approved = HermesLearningCandidateRepository(db).approve(
            candidate_id,
            reviewed_by=actor.name,
            review_note=payload.review_note,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
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
    rejected = HermesLearningCandidateRepository(db).reject(
        candidate_id,
        reviewed_by=actor.name,
        review_note=payload.review_note,
    )
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
    rule = HermesLearningCandidateRepository(db).update_learned_rule_status(
        rule_id,
        status=payload.status,
        note=payload.note,
    )
    if rule is None:
        raise HTTPException(status_code=404, detail="Learned quote rule not found.")
    return learned_quote_rule_to_dict(rule)
