import os
from collections.abc import Callable

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.db.repositories.api_key_repository import APIKeyRepository
from apps.api.db.repositories.user_repository import UserRepository
from apps.api.db.session import get_db
from apps.api.security.tokens import TokenError, decode_access_token


ADMIN_ROLES = ("admin",)
ALL_ROLES = ("admin", "operator", "sales", "viewer")
BACKOFFICE_ROLES = ("admin", "operator", "viewer")
QUOTE_WRITE_ROLES = ("admin", "operator", "sales")
AI_QUOTE_WRITE_ROLES = ("admin", "sales")
MANUAL_TASK_READ_ROLES = ("admin", "operator", "viewer")
MANUAL_TASK_WRITE_ROLES = ("admin", "operator")
AUDIT_READ_ROLES = ("admin", "operator", "viewer")
LEARNING_READ_ROLES = ("admin", "operator", "viewer")
LEARNING_WRITE_ROLES = ("admin", "operator")


class CurrentActor(BaseModel):
    user_id: int | None = None
    api_key_id: int | None
    name: str
    role: str
    tenant_id: str | None = None
    scopes: list[str] = Field(default_factory=list)


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def is_auth_disabled() -> bool:
    return os.getenv("DEV_AUTH_DISABLED", "false").strip().lower() in {"1", "true", "yes", "on"}


def require_roles(
    *allowed_roles: str,
    update_api_key_last_used: bool = True,
    required_scope: str | None = None,
    api_key_only: bool = False,
) -> Callable[..., CurrentActor]:
    def dependency(
        authorization: str | None = Header(default=None, alias="Authorization"),
        x_api_key: str | None = Depends(api_key_header),
        db: Session = Depends(get_db),
    ) -> CurrentActor:
        if is_auth_disabled():
            return CurrentActor(user_id=None, api_key_id=None, name="dev-auth-disabled", role="admin")
        if api_key_only and authorization:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="X-API-Key header is required for this action.",
            )
        if authorization:
            actor = _actor_from_authorization(authorization, db)
            if actor.role not in allowed_roles:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="User role is not allowed for this action.",
                )
            return actor
        if not x_api_key:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Authorization bearer token or X-API-Key header is required.",
            )

        record = APIKeyRepository(db).authenticate(
            x_api_key,
            update_last_used=update_api_key_last_used,
        )
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
        scopes = list(record.scopes or [])
        if required_scope and required_scope not in scopes:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"API key scope is required: {required_scope}.",
            )
        return CurrentActor(
            user_id=None,
            api_key_id=record.id,
            name=record.name,
            role=record.role,
            tenant_id=record.tenant_id,
            scopes=scopes,
        )

    return dependency


def _actor_from_authorization(authorization: str, db: Session) -> CurrentActor:
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must use Bearer token.",
        )
    try:
        payload = decode_access_token(token)
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user_id = payload.get("sub")
    if not isinstance(user_id, int):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token subject.")
    record = UserRepository(db).get_user(user_id)
    if record is None or not record.enabled:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User is disabled or not found.")
    return CurrentActor(user_id=record.id, api_key_id=None, name=record.display_name, role=record.role)
