from __future__ import annotations

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import WeComBotConfig
from apps.api.security.secrets import decrypt_secret, encrypt_secret, mask_tail


GROUP_WEBHOOK_BOT_TYPE = "group_webhook"
AIBOT_LONG_CONNECTION_BOT_TYPE = "wecom_aibot_long_connection"
ALLOWED_BOT_TYPES = {GROUP_WEBHOOK_BOT_TYPE, AIBOT_LONG_CONNECTION_BOT_TYPE}
ALLOWED_PURPOSES = {"quote_success", "manual_required", "ai_quote", "manual_resolved", "general"}


class WeComBotConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_config(self, **values: Any) -> WeComBotConfig:
        webhook_url = values.pop("webhook_url", None)
        secret = values.pop("secret", None)
        self._validate_choice(values)
        self._validate_required_secret_values(values, webhook_url=webhook_url, secret=secret, is_create=True)
        if values.get("is_default"):
            self._clear_default()
        record = WeComBotConfig(
            **values,
            webhook_url_encrypted=encrypt_secret(str(webhook_url)) if webhook_url else None,
            secret_encrypted=encrypt_secret(str(secret)) if secret else None,
        )
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
        secret = values.pop("secret", None)
        self._validate_choice(values)
        next_values = {
            "bot_type": values.get("bot_type", record.bot_type),
            "bot_id": values.get("bot_id", record.bot_id),
        }
        self._validate_required_secret_values(
            next_values,
            webhook_url=webhook_url or self.decrypt_webhook_url(record),
            secret=secret or self.decrypt_secret_value(record),
            is_create=False,
        )
        if values.get("is_default") is True:
            self._clear_default(except_id=config_id)
        for key, value in values.items():
            setattr(record, key, value)
        if webhook_url:
            record.webhook_url_encrypted = encrypt_secret(str(webhook_url))
        if secret:
            record.secret_encrypted = encrypt_secret(str(secret))
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

    def decrypt_webhook_url(self, record: WeComBotConfig) -> str | None:
        if not record.webhook_url_encrypted:
            return None
        return decrypt_secret(record.webhook_url_encrypted)

    def decrypt_secret_value(self, record: WeComBotConfig) -> str | None:
        if not record.secret_encrypted:
            return None
        return decrypt_secret(record.secret_encrypted)

    def to_public_dict(self, record: WeComBotConfig) -> dict[str, object]:
        return {
            "id": record.id,
            "name": record.name,
            "masked_webhook_url": mask_webhook_url(self.decrypt_webhook_url(record)),
            "masked_bot_id": mask_tail(record.bot_id, prefix_length=6, tail_length=6),
            "has_secret": bool(record.secret_encrypted),
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

    def _validate_required_secret_values(
        self,
        values: dict[str, Any],
        *,
        webhook_url: str | None,
        secret: str | None,
        is_create: bool,
    ) -> None:
        bot_type = values.get("bot_type") or GROUP_WEBHOOK_BOT_TYPE
        bot_id = values.get("bot_id")
        if bot_type == GROUP_WEBHOOK_BOT_TYPE:
            if not webhook_url:
                raise ValueError("webhook_url is required for group_webhook bots.")
            return
        if bot_type == AIBOT_LONG_CONNECTION_BOT_TYPE:
            if not bot_id:
                raise ValueError("bot_id is required for wecom_aibot_long_connection bots.")
            if not secret:
                raise ValueError("secret is required for wecom_aibot_long_connection bots.")
            return


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
