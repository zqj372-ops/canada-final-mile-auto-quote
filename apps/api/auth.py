import os
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from apps.api.db.repositories.api_key_repository import APIKeyRepository
from apps.api.db.session import get_db


ADMIN_ROLES = ("admin",)
QUOTE_WRITE_ROLES = ("admin", "operator", "sales")
AI_QUOTE_WRITE_ROLES = ("admin", "sales")
MANUAL_TASK_READ_ROLES = ("admin", "operator", "viewer")
MANUAL_TASK_WRITE_ROLES = ("admin", "operator")
AUDIT_READ_ROLES = ("admin", "operator", "viewer")


class CurrentActor(BaseModel):
    api_key_id: int | None
    name: str
    role: str


def is_auth_disabled() -> bool:
    return os.getenv("DEV_AUTH_DISABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def require_roles(*allowed_roles: str) -> Callable[..., CurrentActor]:
    def dependency(
        x_api_key: str | None = Header(default=None, alias="X-API-Key"),
        db: Session = Depends(get_db),
    ) -> CurrentActor:
        if is_auth_disabled():
            return CurrentActor(api_key_id=None, name="dev-auth-disabled", role="admin")
        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key header is required.",
            )

        record = APIKeyRepository(db).authenticate(x_api_key)
        if record is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or disabled API key.",
            )
        if record.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="API key role is not allowed for this action.",
            )
        return CurrentActor(api_key_id=record.id, name=record.name, role=record.role)

    return dependency
