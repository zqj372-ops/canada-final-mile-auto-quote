from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.models import EmailNotificationConfig
from apps.api.db.repositories.email_notification_config_repository import EmailNotificationConfigRepository
from apps.api.db.session import get_db
from packages.email_notifier.client import SmtpEmailClient


router = APIRouter(prefix="/email/configs", tags=["email"], dependencies=[Depends(require_roles(*ADMIN_ROLES))])


class EmailNotificationConfigCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    smtp_host: str = Field(min_length=1, max_length=255)
    smtp_port: int = Field(default=587, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1)
    from_email: str = Field(min_length=3, max_length=255)
    from_name: str | None = Field(default=None, max_length=128)
    recipient_emails: list[str] = Field(min_length=1)
    use_tls: bool = True
    use_ssl: bool = False
    purpose: str = "general"
    enabled: bool = True
    is_default: bool = False


class EmailNotificationConfigUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=128)
    smtp_host: str | None = Field(default=None, min_length=1, max_length=255)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = Field(default=None, min_length=1, max_length=255)
    password: str | None = Field(default=None, min_length=1)
    from_email: str | None = Field(default=None, min_length=3, max_length=255)
    from_name: str | None = Field(default=None, max_length=128)
    recipient_emails: list[str] | None = None
    use_tls: bool | None = None
    use_ssl: bool | None = None
    purpose: str | None = None
    enabled: bool | None = None
    is_default: bool | None = None


@router.get("")
def list_email_configs(db: Session = Depends(get_db)) -> list[dict[str, object]]:
    repository = EmailNotificationConfigRepository(db)
    return [repository.to_public_dict(record) for record in repository.list_configs()]


@router.post("", status_code=201)
def create_email_config(payload: EmailNotificationConfigCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = EmailNotificationConfigRepository(db)
    try:
        record = repository.create_config(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_public_dict(record)


@router.get("/{config_id}")
def get_email_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = EmailNotificationConfigRepository(db)
    record = _get_config_or_404(repository, config_id)
    return repository.to_public_dict(record)


@router.patch("/{config_id}")
def update_email_config(
    config_id: int,
    payload: EmailNotificationConfigUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = EmailNotificationConfigRepository(db)
    try:
        record = repository.update_config(config_id, **payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Email notification config not found.")
    return repository.to_public_dict(record)


@router.delete("/{config_id}")
def delete_email_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, bool]:
    repository = EmailNotificationConfigRepository(db)
    if not repository.delete_config(config_id):
        raise HTTPException(status_code=404, detail="Email notification config not found.")
    return {"deleted": True}


@router.post("/{config_id}/set-default")
def set_default_email_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = EmailNotificationConfigRepository(db)
    record = repository.set_default_config(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Email notification config not found.")
    return repository.to_public_dict(record)


@router.post("/{config_id}/test")
def test_email_config(config_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    repository = EmailNotificationConfigRepository(db)
    record = _get_config_or_404(repository, config_id)
    if not record.enabled:
        return {"success": False, "error": "Email config is disabled.", "latency_ms": 0, "status_code": None}
    password = repository.decrypt_password(record)
    result = SmtpEmailClient(
        smtp_host=record.smtp_host,
        smtp_port=record.smtp_port,
        username=record.username,
        password=password,
        from_email=record.from_email,
        from_name=record.from_name,
        use_tls=record.use_tls,
        use_ssl=record.use_ssl,
    ).send(
        subject="[Canada Quote] 邮件通知测试",
        body_text="加拿大尾端自动报价系统：邮件通知连接测试成功。\n",
        to_emails=list(record.recipient_emails or []),
    )
    return result.model_dump()


def _get_config_or_404(
    repository: EmailNotificationConfigRepository,
    config_id: int,
) -> EmailNotificationConfig:
    record = repository.get_config(config_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Email notification config not found.")
    return record
