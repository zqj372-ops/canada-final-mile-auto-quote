from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import WeComBotConfig
from apps.api.security.secrets import decrypt_secret, encrypt_secret


ALLOWED_BOT_TYPES = {"group_webhook"}
ALLOWED_PURPOSES = {"quote_success", "manual_required", "ai_quote", "manual_resolved", "general"}


class WeComBotConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_config(self, **values: Any) -> WeComBotConfig:
        webhook_url = values.pop("webhook_url", None)
        if not webhook_url:
            raise ValueError("webhook_url is required.")
        self._validate_choice(values)
        if values.get("is_default"):
            self._clear_default()
        record = WeComBotConfig(**values, webhook_url_encrypted=encrypt_secret(str(webhook_url)))
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_configs(self) -> list[WeComBotConfig]:
        return list(self.session.scalars(select(WeComBotConfig).order_by(WeComBotConfig.id.asc())))

    def get_config(self, config_id: int) -> WeComBotConfig | None:
        return self.session.get(WeComBotConfig, config_id)

    def update_config(self, config_id: int, **values: Any) -> WeComBotConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None
        webhook_url = values.pop("webhook_url", None)
        self._validate_choice(values)
        if values.get("is_default") is True:
            self._clear_default(except_id=config_id)
        for key, value in values.items():
            setattr(record, key, value)
        if webhook_url:
            record.webhook_url_encrypted = encrypt_secret(str(webhook_url))
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

    def get_default_config(self) -> WeComBotConfig | None:
        statement = select(WeComBotConfig).where(
            WeComBotConfig.is_default.is_(True),
            WeComBotConfig.enabled.is_(True),
        )
        return self.session.scalars(statement.order_by(WeComBotConfig.id.asc())).first()

    def get_by_purpose(self, purpose: str) -> WeComBotConfig | None:
        exact = self.session.scalars(
            select(WeComBotConfig)
            .where(
                WeComBotConfig.enabled.is_(True),
                WeComBotConfig.purpose == purpose,
            )
            .order_by(WeComBotConfig.is_default.desc(), WeComBotConfig.id.asc())
        ).first()
        if exact:
            return exact
        return self.get_default_config()

    def set_default_config(self, config_id: int) -> WeComBotConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None
        self._clear_default(except_id=config_id)
        record.is_default = True
        self.session.commit()
        self.session.refresh(record)
        return record

    def decrypt_webhook_url(self, record: WeComBotConfig) -> str:
        return decrypt_secret(record.webhook_url_encrypted)

    def to_public_dict(self, record: WeComBotConfig) -> dict[str, object]:
        return {
            "id": record.id,
            "name": record.name,
            "masked_webhook_url": mask_webhook_url(self.decrypt_webhook_url(record)),
            "bot_type": record.bot_type,
            "purpose": record.purpose,
            "enabled": record.enabled,
            "is_default": record.is_default,
            "mention_all_on_manual_required": record.mention_all_on_manual_required,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _clear_default(self, *, except_id: int | None = None) -> None:
        for record in self.session.scalars(select(WeComBotConfig).where(WeComBotConfig.is_default.is_(True))):
            if except_id is not None and record.id == except_id:
                continue
            record.is_default = False

    def _validate_choice(self, values: dict[str, Any]) -> None:
        bot_type = values.get("bot_type")
        if bot_type is not None and bot_type not in ALLOWED_BOT_TYPES:
            raise ValueError(f"Unsupported bot_type: {bot_type}")
        purpose = values.get("purpose")
        if purpose is not None and purpose not in ALLOWED_PURPOSES:
            raise ValueError(f"Unsupported purpose: {purpose}")


def mask_webhook_url(webhook_url: str | None) -> str | None:
    if not webhook_url:
        return None
    parts = urlsplit(webhook_url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    masked_query = []
    for key, value in query:
        if key.lower() == "key":
            masked_query.append((key, f"****{value[-4:]}" if len(value) >= 4 else "****"))
        else:
            masked_query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(masked_query, safe="*"), parts.fragment))
