from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.session import get_db
from packages.quote_engine.workbench_config import QuoteWorkbenchConfig


CONFIG_READ_ROLES = ("admin", "operator", "sales", "viewer")

router = APIRouter(prefix="/quote-configs", tags=["quote-configs"])


@router.get(
    "/workbench",
    response_model=QuoteWorkbenchConfig,
    dependencies=[Depends(require_roles(*CONFIG_READ_ROLES))],
)
def get_workbench_config(db: Session = Depends(get_db)) -> QuoteWorkbenchConfig:
    return QuoteRuleConfigRepository(db).get_workbench_config()


@router.put(
    "/workbench",
    response_model=QuoteWorkbenchConfig,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def update_workbench_config(
    payload: QuoteWorkbenchConfig,
    db: Session = Depends(get_db),
) -> QuoteWorkbenchConfig:
    return QuoteRuleConfigRepository(db).save_workbench_config(payload)
