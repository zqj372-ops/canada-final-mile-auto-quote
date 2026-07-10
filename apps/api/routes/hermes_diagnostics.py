from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import LEARNING_READ_ROLES, LEARNING_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.hermes_diagnostic_service import (
    HermesDiagnosticSuggestionPayload,
    fail_hermes_diagnostic,
    get_hermes_diagnostic,
    list_hermes_diagnostics,
    run_hermes_diagnostic,
    submit_hermes_diagnostic_suggestion,
)
from apps.api.services.batch_diagnostic_report_service import (
    get_batch_diagnostic_report,
    list_batch_diagnostic_reports,
)


router = APIRouter(prefix="/quotes", tags=["hermes-diagnostics"])


class HermesDiagnosticFailurePayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    error: str = Field(min_length=1, max_length=1000)


@router.get("/hermes-diagnostics", dependencies=[Depends(require_roles(*LEARNING_READ_ROLES))])
def list_diagnostics(
    db: Session = Depends(get_db),
    status: str | None = None,
    quote_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    return list_hermes_diagnostics(db, status=status, quote_id=quote_id, limit=limit)


@router.get("/batch-diagnostic-reports", dependencies=[Depends(require_roles(*LEARNING_READ_ROLES))])
def list_batch_reports(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    return list_batch_diagnostic_reports(db)


@router.get("/batch-diagnostic-reports/{batch_id}", dependencies=[Depends(require_roles(*LEARNING_READ_ROLES))])
def get_batch_report(batch_id: str, db: Session = Depends(get_db)) -> dict[str, object]:
    return get_batch_diagnostic_report(db, batch_id)


@router.get("/hermes-diagnostics/{diagnostic_id}", dependencies=[Depends(require_roles(*LEARNING_READ_ROLES))])
def get_diagnostic(diagnostic_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    return get_hermes_diagnostic(db, diagnostic_id)


@router.post("/hermes-diagnostics/{diagnostic_id}/suggestion", dependencies=[Depends(require_roles(*LEARNING_WRITE_ROLES))])
def submit_diagnostic_suggestion(
    diagnostic_id: int,
    payload: HermesDiagnosticSuggestionPayload,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return submit_hermes_diagnostic_suggestion(db, diagnostic_id, payload)


@router.post("/hermes-diagnostics/{diagnostic_id}/run", dependencies=[Depends(require_roles(*LEARNING_WRITE_ROLES))])
def run_diagnostic(
    diagnostic_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return run_hermes_diagnostic(db, diagnostic_id)


@router.post("/hermes-diagnostics/{diagnostic_id}/fail", dependencies=[Depends(require_roles(*LEARNING_WRITE_ROLES))])
def fail_diagnostic(
    diagnostic_id: int,
    payload: HermesDiagnosticFailurePayload,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return fail_hermes_diagnostic(db, diagnostic_id, error=payload.error)
