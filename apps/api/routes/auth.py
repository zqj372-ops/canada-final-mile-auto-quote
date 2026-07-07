from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ALL_ROLES, BACKOFFICE_ROLES, CurrentActor, require_roles
from apps.api.db.repositories.user_repository import UserRepository
from apps.api.db.session import get_db
from apps.api.security.tokens import DEFAULT_TOKEN_TTL_SECONDS, create_access_token


router = APIRouter(prefix="/auth", tags=["auth"])


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    actor: CurrentActor


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResponse:
    user = UserRepository(db).authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误。",
        )
    actor = CurrentActor(user_id=user.id, api_key_id=None, name=user.display_name, role=user.role)
    token = create_access_token({"sub": user.id, "role": user.role})
    return LoginResponse(
        access_token=token,
        expires_in_seconds=DEFAULT_TOKEN_TTL_SECONDS,
        actor=actor,
    )


@router.get("/me", response_model=CurrentActor)
def get_current_actor(actor: CurrentActor = Depends(require_roles(*ALL_ROLES))) -> CurrentActor:
    return actor


@router.get("/backoffice", response_model=CurrentActor)
def get_backoffice_actor(actor: CurrentActor = Depends(require_roles(*BACKOFFICE_ROLES))) -> CurrentActor:
    return actor
