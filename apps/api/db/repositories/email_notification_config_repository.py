from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import EmailNotificationConfig
from apps.api.security.secrets import decrypt_secret, encrypt_secret, mask_tail


ALLOWED_PURPOSES = {"quote_success", "manual_required", "ai_quote", "manual_resolved", "general"}


class EmailNotificationConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_config(self, **values: Any) -> EmailNotificationConfig:
        password = values.pop("password", None)
        self._validate_values(values, require_recipients=True)
        if values.get("is_default"):
            self._clear_default()
        record = EmailNotificationConfig(
            **values,
            password_encrypted=encrypt_secret(str(password)) if password else None,
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_configs(self) -> list[EmailNotificationConfig]:
        return list(self.session.scalars(select(EmailNotificationConfig).order_by(EmailNotificationConfig.id.asc())))

    def get_config(self, config_id: int) -> EmailNotificationConfig | None:
        return self.session.get(EmailNotificationConfig, config_id)

    def update_config(self, config_id: int, **values: Any) -> EmailNotificationConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None
        password = values.pop("password", None)
        self._validate_values(values, require_recipients=False)
        if values.get("is_default") is True:
            self._clear_default(except_id=config_id)
        for key, value in values.items():
            setattr(record, key, value)
        if password:
            record.password_encrypted = encrypt_secret(str(password))
        self.session.commit()
        self.session.refresh(record)
        return record

    def delete_config(self, config_id: int) -> bool:
        record = self.get_config(config_id)
        if record is None:
            return False
        self.session.delete(record)
        self.session.commit()
        return True

    def get_default_config(self) -> EmailNotificationConfig | None:
        statement = select(EmailNotificationConfig).where(
            EmailNotificationConfig.is_default.is_(True),
            EmailNotificationConfig.enabled.is_(True),
        )
        return self.session.scalars(statement.order_by(EmailNotificationConfig.id.asc())).first()

    def get_by_purpose(self, purpose: str) -> EmailNotificationConfig | None:
        exact = self.session.scalars(
            select(EmailNotificationConfig)
            .where(
                EmailNotificationConfig.enabled.is_(True),
                EmailNotificationConfig.purpose == purpose,
            )
            .order_by(EmailNotificationConfig.is_default.desc(), EmailNotificationConfig.id.asc())
        ).first()
        if exact:
            return exact
        return self.get_default_config()

    def set_default_config(self, config_id: int) -> EmailNotificationConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None
        self._clear_default(except_id=config_id)
        record.is_default = True
        self.session.commit()
        self.session.refresh(record)
        return record

    def decrypt_password(self, record: EmailNotificationConfig) -> str | None:
        if not record.password_encrypted:
            return None
        return decrypt_secret(record.password_encrypted)

    def to_public_dict(self, record: EmailNotificationConfig) -> dict[str, object]:
        return {
            "id": record.id,
            "name": record.name,
            "smtp_host": record.smtp_host,
            "smtp_port": record.smtp_port,
            "masked_username": mask_tail(record.username, prefix_length=3, tail_length=4),
            "has_password": bool(record.password_encrypted),
            "from_email": record.from_email,
            "from_name": record.from_name,
            "recipient_emails": record.recipient_emails,
            "use_tls": record.use_tls,
            "use_ssl": record.use_ssl,
            "purpose": record.purpose,
            "enabled": record.enabled,
            "is_default": record.is_default,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _clear_default(self, *, except_id: int | None = None) -> None:
        for record in self.session.scalars(
            select(EmailNotificationConfig).where(EmailNotificationConfig.is_default.is_(True))
        ):
            if except_id is not None and record.id == except_id:
                continue
            record.is_default = False

    def _validate_values(self, values: dict[str, Any], *, require_recipients: bool) -> None:
        purpose = values.get("purpose")
        if purpose is not None and purpose not in ALLOWED_PURPOSES:
            raise ValueError(f"Unsupported purpose: {purpose}")
        port = values.get("smtp_port")
        if port is not None and not (1 <= int(port) <= 65535):
            raise ValueError("smtp_port must be between 1 and 65535.")
        recipients = values.get("recipient_emails")
        if recipients is None:
            if require_recipients:
                raise ValueError("recipient_emails is required.")
            return
        if not isinstance(recipients, list) or not recipients:
            raise ValueError("recipient_emails must contain at least one email.")
        clean = []
        for email in recipients:
            if not isinstance(email, str) or "@" not in email:
                raise ValueError("recipient_emails contains an invalid email.")
            clean.append(email.strip())
        values["recipient_emails"] = clean
