from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.models import WeComBotConfig
from apps.api.db.repositories.wecom_bot_config_repository import WeComBotConfigRepository
from apps.api.db.session import get_db
from packages.wecom.bot_client import WeComAIBotLongConnectionClient, WeComBotClient


router = APIRouter(prefix="/wecom/bots", tags=["wecom"], dependencies=[Depends(require_roles(*ADMIN_ROLES))])


class WeComBotConfigCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    webhook_url: str | None = Field(default=None, min_length=1)
    bot_id: str | None = Field(default=None, min_length=1, max_length=128)
    secret: str | None = Field(default=None, min_length=1)
    bot_type: str = "group_webhook"
    purpose: str = "general"
    enabled: bool = True
    is_default: bool = False
    mention_all_on_manual_required: bool = False


class WeComBotConfigUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    webhook_url: str | None = Field(default=None, min_length=1)
    bot_id: str | None = Field(default=None, min_length=1, max_length=128)
    secret: str | None = Field(default=None, min_length=1)
    bot_type: str | None = None
    purpose: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None
    mention_all_on_manual_required: bool | None = None


@router.get("")
def list_wecom_bots(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    repository = WeComBotConfigRepository(db)
    return [repository.to_public_dict(record) for record in repository.list_configs()]


@router.post("", status_code=201)
def create_wecom_bot(payload: WeComBotConfigCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = WeComBotConfigRepository(db)
    try:
        record = repository.create_config(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_public_dict(record)


@router.get("/{bot_id}")
def get_wecom_bot(bot_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = WeComBotConfigRepository(db)
    record = _get_bot_or_404(repository, bot_id)
    return repository.to_public_dict(record)


@router.patch("/{bot_id}")
def update_wecom_bot(
    bot_id: int,
    payload: WeComBotConfigUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = WeComBotConfigRepository(db)
    try:
        record = repository.update_config(bot_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="WeCom bot config not found.")
    return repository.to_public_dict(record)


@router.delete("/{bot_id}")
def delete_wecom_bot(bot_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    repository = WeComBotConfigRepository(db)
    if not repository.delete_config(bot_id):
        raise HTTPException(status_code=404, detail="WeCom bot config not found.")
    return {"deleted": True}


@router.post("/{bot_id}/set-default")
def set_default_wecom_bot(bot_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = WeComBotConfigRepository(db)
    record = repository.set_default_config(bot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="WeCom bot config not found.")
    return repository.to_public_dict(record)


@router.post("/{bot_id}/test")
def test_wecom_bot(bot_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = WeComBotConfigRepository(db)
    record = _get_bot_or_404(repository, bot_id)
    if not record.enabled:
        return {"success": False, "error": "WeCom bot config is disabled.", "latency_ms": 0, "status_code": None}
    if record.bot_type == "wecom_aibot_long_connection":
        secret = repository.decrypt_secret_value(record)
        if not record.bot_id or not secret:
            return {"success": False, "error": "WeCom AIBot credentials are incomplete.", "latency_ms": 0, "status_code": None}
        result = WeComAIBotLongConnectionClient(record.bot_id, secret).test_connection()
        return result.model_dump()
    webhook_url = repository.decrypt_webhook_url(record)
    if not webhook_url:
        return {"success": False, "error": "WeCom webhook URL is not configured.", "latency_ms": 0, "status_code": None}
    result = WeComBotClient(webhook_url).test_webhook()
    return result.model_dump()


def _get_bot_or_404(repository: WeComBotConfigRepository, bot_id: int) -> WeComBotConfig:
    record = repository.get_config(bot_id)
    if record is None:
        raise HTTPException(status_code=404, detail="WeCom bot config not found.")
    return record
