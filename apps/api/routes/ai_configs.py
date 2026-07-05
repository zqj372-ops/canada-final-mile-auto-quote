from time import perf_counter

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.models import AIModelConfig as AIModelConfigRecord
from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
from apps.api.db.session import get_db
from packages.ai_assistant.model_client import AIMessage, OpenAICompatibleClient, config_from_record


router = APIRouter(prefix="/ai-configs", tags=["ai-configs"], dependencies=[Depends(require_roles(*ADMIN_ROLES))])


class AIModelConfigCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    provider: str = Field(default="openai")
    base_url: str | None = None
    api_key: str | None = None
    model_name: str = Field(min_length=1, max_length=128)
    temperature: float = Field(default=0, ge=0, le=2)
    max_tokens: int = Field(default=800, ge=1, le=20000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    is_default: bool = False
    enabled: bool = True
    purpose: str = Field(default="general")


class AIModelConfigUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    provider: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    model_name: str | None = Field(default=None, min_length=1, max_length=128)
    temperature: float | None = Field(default=None, ge=0, le=2)
    max_tokens: int | None = Field(default=None, ge=1, le=20000)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    is_default: bool | None = None
    enabled: bool | None = None
    purpose: str | None = None


@router.get("")
def list_ai_configs(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    repository = AIModelConfigRepository(db)
    return [repository.to_public_dict(record) for record in repository.list_configs()]


@router.post("", status_code=201)
def create_ai_config(payload: AIModelConfigCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = AIModelConfigRepository(db)
    try:
        record = repository.create_config(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_public_dict(record)


@router.get("/{config_id}")
def get_ai_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = AIModelConfigRepository(db)
    record = _get_record_or_404(repository, config_id)
    return repository.to_public_dict(record)


@router.patch("/{config_id}")
def update_ai_config(
    config_id: int,
    payload: AIModelConfigUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = AIModelConfigRepository(db)
    values = payload.model_dump(exclude_unset=True)
    try:
        record = repository.update_config(config_id, **values)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="AI model config not found.")
    return repository.to_public_dict(record)


@router.delete("/{config_id}")
def delete_ai_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    repository = AIModelConfigRepository(db)
    if not repository.delete_config(config_id):
        raise HTTPException(status_code=404, detail="AI model config not found.")
    return {"deleted": True}


@router.post("/{config_id}/set-default")
def set_default_ai_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = AIModelConfigRepository(db)
    record = repository.set_default_config(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail="AI model config not found.")
    return repository.to_public_dict(record)


@router.post("/{config_id}/test")
def test_ai_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = AIModelConfigRepository(db)
    record = _get_record_or_404(repository, config_id)
    config = config_from_record(record, api_key=repository.decrypt_api_key(record))
    client = OpenAICompatibleClient(config)

    started = perf_counter()
    response = client.complete(
        [
            AIMessage(role="system", content="Return the word ok."),
            AIMessage(role="user", content="ok"),
        ]
    )
    latency_ms = int((perf_counter() - started) * 1000)
    if response.error:
        return {"success": False, "error": response.error, "latency_ms": response.latency_ms or latency_ms}
    return {
        "success": True,
        "error": None,
        "latency_ms": response.latency_ms or latency_ms,
        "preview": response.content[:80],
    }


def _get_record_or_404(repository: AIModelConfigRepository, config_id: int) -> AIModelConfigRecord:
    record = repository.get_config(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail="AI model config not found.")
    return record
