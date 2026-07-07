from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.repositories.user_repository import UserRepository
from apps.api.db.session import get_db


router = APIRouter(
    prefix="/users",
    tags=["users"],
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)


class UserCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=8, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str = Field(default="sales", pattern="^(admin|operator|sales|viewer)$")
    enabled: bool = True


class UserUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    password: str | None = Field(default=None, min_length=8, max_length=256)
    display_name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = Field(default=None, pattern="^(admin|operator|sales|viewer)$")
    enabled: bool | None = None


@router.get("")
def list_users(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    repository = UserRepository(db)
    return [repository.to_public_dict(record) for record in repository.list_users()]


@router.post("", status_code=201)
def create_user(payload: UserCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = UserRepository(db)
    try:
        record = repository.create_user(**payload.model_dump())
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="用户名已存在。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_public_dict(record)


@router.patch("/{user_id}")
def update_user(user_id: int, payload: UserUpdate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = UserRepository(db)
    try:
        record = repository.update_user(user_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="User not found.")
    return repository.to_public_dict(record)
