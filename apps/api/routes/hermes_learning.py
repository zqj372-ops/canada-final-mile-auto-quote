from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor, LEARNING_READ_ROLES, LEARNING_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.hermes_learning_service import (
    HermesCandidateReviewPayload,
    LearnedRuleUpdatePayload,
    approve_hermes_candidate as approve_hermes_candidate_service,
    get_hermes_candidate as get_hermes_candidate_service,
    list_hermes_candidates as list_hermes_candidates_service,
    reject_hermes_candidate as reject_hermes_candidate_service,
    update_learned_rule as update_learned_rule_service,
)


router = APIRouter(prefix="/quotes", tags=["hermes-learning"])


@router.get("/learning-candidates", dependencies=[Depends(require_roles(*LEARNING_READ_ROLES))])
def list_hermes_candidates(
    db: Session = Depends(get_db),
    status: str | None = None,
    postal_prefix: str | None = None,
    city: str | None = None,
    province: str | None = None,
    billing_pallets: int | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    return list_hermes_candidates_service(
        db,
        status=status,
        postal_prefix=postal_prefix,
        city=city,
        province=province,
        billing_pallets=billing_pallets,
        limit=limit,
    )


@router.get("/learning-candidates/{candidate_id}", dependencies=[Depends(require_roles(*LEARNING_READ_ROLES))])
def get_hermes_candidate(candidate_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    return get_hermes_candidate_service(db, candidate_id)


@router.post("/learning-candidates/{candidate_id}/approve")
def approve_hermes_candidate(
    candidate_id: int,
    payload: HermesCandidateReviewPayload,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*LEARNING_WRITE_ROLES)),
) -> dict[str, object]:
    return approve_hermes_candidate_service(db, candidate_id, payload, actor)


@router.post("/learning-candidates/{candidate_id}/reject")
def reject_hermes_candidate(
    candidate_id: int,
    payload: HermesCandidateReviewPayload,
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*LEARNING_WRITE_ROLES)),
) -> dict[str, object]:
    return reject_hermes_candidate_service(db, candidate_id, payload, actor)


@router.patch("/learned-rules/{rule_id}", dependencies=[Depends(require_roles(*LEARNING_WRITE_ROLES))])
def update_learned_rule(
    rule_id: int,
    payload: LearnedRuleUpdatePayload,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return update_learned_rule_service(db, rule_id, payload)
