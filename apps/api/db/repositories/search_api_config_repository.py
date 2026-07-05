from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import SearchApiConfig
from apps.api.security.secrets import decrypt_secret, encrypt_secret, mask_tail


ALLOWED_SEARCH_PROVIDERS = {"tavily", "custom"}
ALLOWED_SEARCH_PURPOSES = {"address_research", "market_research", "general"}


class SearchApiConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_config(self, **values: Any) -> SearchApiConfig:
        api_key = values.pop("api_key", None)
        if not api_key:
            raise ValueError("api_key is required.")
        self._validate_choice(values)
        if values.get("is_default"):
            self._clear_default()
        record = SearchApiConfig(**values, api_key_encrypted=encrypt_secret(str(api_key)))
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_configs(self) -> list[SearchApiConfig]:
        return list(self.session.scalars(select(SearchApiConfig).order_by(SearchApiConfig.id.asc())))

    def get_config(self, config_id: int) -> SearchApiConfig | None:
        return self.session.get(SearchApiConfig, config_id)

    def update_config(self, config_id: int, **values: Any) -> SearchApiConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None

        api_key = values.pop("api_key", None)
        self._validate_choice(values)
        if values.get("is_default") is True:
            self._clear_default(except_id=config_id)

        for key, value in values.items():
            setattr(record, key, value)
        if api_key:
            record.api_key_encrypted = encrypt_secret(str(api_key))

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

    def get_default_config(self) -> SearchApiConfig | None:
        statement = select(SearchApiConfig).where(SearchApiConfig.is_default.is_(True), SearchApiConfig.enabled.is_(True))
        return self.session.scalars(statement.order_by(SearchApiConfig.id.asc())).first()

    def set_default_config(self, config_id: int) -> SearchApiConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None
        self._clear_default(except_id=config_id)
        record.is_default = True
        self.session.commit()
        self.session.refresh(record)
        return record

    def decrypt_api_key(self, record: SearchApiConfig) -> str:
        return decrypt_secret(record.api_key_encrypted) or ""

    def to_public_dict(self, record: SearchApiConfig) -> dict[str, object]:
        return {
            "id": record.id,
            "name": record.name,
            "provider": record.provider,
            "base_url": record.base_url,
            "masked_api_key": mask_tail(self.decrypt_api_key(record), prefix_length=3, tail_length=4),
            "purpose": record.purpose,
            "enabled": record.enabled,
            "is_default": record.is_default,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _clear_default(self, *, except_id: int | None = None) -> None:
        for record in self.session.scalars(select(SearchApiConfig).where(SearchApiConfig.is_default.is_(True))):
            if except_id is not None and record.id == except_id:
                continue
            record.is_default = False

    def _validate_choice(self, values: dict[str, Any]) -> None:
        provider = values.get("provider")
        if provider is not None and provider not in ALLOWED_SEARCH_PROVIDERS:
            raise ValueError(f"Unsupported search provider: {provider}")
        purpose = values.get("purpose")
        if purpose is not None and purpose not in ALLOWED_SEARCH_PURPOSES:
            raise ValueError(f"Unsupported search purpose: {purpose}")
