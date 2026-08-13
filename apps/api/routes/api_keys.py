from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.repositories.api_key_repository import APIKeyRepository
from apps.api.db.session import get_db


router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)


class APIKeyCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    role: str = Field(pattern="^(admin|operator|sales|viewer)$")
    tenant_id: str = Field(default="default", min_length=1, max_length=128)
    scopes: list[str] = Field(default_factory=list)
    enabled: bool = True


class APIKeyUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    role: str | None = Field(default=None, pattern="^(admin|operator|sales|viewer)$")
    tenant_id: str | None = Field(default=None, min_length=1, max_length=128)
    scopes: list[str] | None = None
    enabled: bool | None = None


@router.get("")
def list_api_keys(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    repository = APIKeyRepository(db)
    return [repository.to_public_dict(record) for record in repository.list_keys()]


@router.post("", status_code=201)
def create_api_key(payload: APIKeyCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = APIKeyRepository(db)
    try:
        record, plain_key = repository.create_key(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_public_dict(record, plain_key=plain_key)


@router.patch("/{key_id}")
def update_api_key(key_id: int, payload: APIKeyUpdate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = APIKeyRepository(db)
    try:
        record = repository.update_key(key_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="API key not found.")
    return repository.to_public_dict(record)
