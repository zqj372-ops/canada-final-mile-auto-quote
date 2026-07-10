from __future__ import annotations

from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from apps.api.db.models import AIAgentModelAssignment, AIModelConfig
from apps.api.security.secrets import decrypt_secret, encrypt_secret, mask_tail
from packages.ai_assistant.provider_catalog import PROVIDER_PRESETS


ALLOWED_PROVIDERS = set(PROVIDER_PRESETS)
ALLOWED_PURPOSES = {"field_extraction", "sales_note", "address_type", "general"}
ALLOWED_AGENT_KEYS = {"hermes"}


class AIModelConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def create_config(self, **values: Any) -> AIModelConfig:
        api_key = values.pop("api_key", None)
        self._validate_choice(values)
        is_default = bool(values.get("is_default"))
        if is_default:
            self._clear_default()
        record = AIModelConfig(**values)
        if api_key:
            record.api_key_encrypted = encrypt_secret(str(api_key))
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def create_agent_config(self, agent_key: str, **values: Any) -> AIModelConfig:
        self._validate_agent_key(agent_key)
        api_key = values.pop("api_key", None)
        self._validate_choice(values)
        if not values.get("enabled", True):
            raise ValueError("Disabled AI model config cannot be assigned to an agent.")
        if values.get("is_default"):
            self._clear_default()

        record = AIModelConfig(**values)
        if api_key:
            record.api_key_encrypted = encrypt_secret(str(api_key))
        self.session.add(record)
        self.session.flush()

        assignment = self.session.get(AIAgentModelAssignment, agent_key)
        if assignment is None:
            assignment = AIAgentModelAssignment(agent_key=agent_key, ai_model_config_id=record.id)
            self.session.add(assignment)
        else:
            assignment.ai_model_config_id = record.id
        self.session.commit()
        self.session.refresh(record)
        return record

    def list_configs(self) -> list[AIModelConfig]:
        return list(self.session.scalars(select(AIModelConfig).order_by(AIModelConfig.id.asc())))

    def get_config(self, config_id: int) -> AIModelConfig | None:
        return self.session.get(AIModelConfig, config_id)

    def update_config(self, config_id: int, **values: Any) -> AIModelConfig | None:
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
        self.session.execute(
            delete(AIAgentModelAssignment).where(AIAgentModelAssignment.ai_model_config_id == config_id)
        )
        self.session.delete(record)
        self.session.commit()
        return True

    def get_agent_config(self, agent_key: str) -> AIModelConfig | None:
        self._validate_agent_key(agent_key)
        statement = (
            select(AIModelConfig)
            .join(
                AIAgentModelAssignment,
                AIAgentModelAssignment.ai_model_config_id == AIModelConfig.id,
            )
            .where(
                AIAgentModelAssignment.agent_key == agent_key,
                AIModelConfig.enabled.is_(True),
            )
        )
        return self.session.scalars(statement).first()

    def set_agent_config(self, agent_key: str, config_id: int) -> AIModelConfig | None:
        self._validate_agent_key(agent_key)
        record = self.get_config(config_id)
        if record is None:
            return None
        if not record.enabled:
            raise ValueError("Disabled AI model config cannot be assigned to an agent.")

        assignment = self.session.get(AIAgentModelAssignment, agent_key)
        if assignment is None:
            assignment = AIAgentModelAssignment(agent_key=agent_key, ai_model_config_id=config_id)
            self.session.add(assignment)
        else:
            assignment.ai_model_config_id = config_id
        self.session.commit()
        self.session.refresh(record)
        return record

    def get_default_config(self, *, purpose: str | None = None) -> AIModelConfig | None:
        statement = select(AIModelConfig).where(AIModelConfig.is_default.is_(True), AIModelConfig.enabled.is_(True))
        if purpose:
            statement = statement.where(AIModelConfig.purpose.in_([purpose, "general"]))
        return self.session.scalars(statement.order_by(AIModelConfig.id.asc())).first()

    def set_default_config(self, config_id: int) -> AIModelConfig | None:
        record = self.get_config(config_id)
        if record is None:
            return None
        self._clear_default(except_id=config_id)
        record.is_default = True
        self.session.commit()
        self.session.refresh(record)
        return record

    def decrypt_api_key(self, record: AIModelConfig) -> str | None:
        if not record.api_key_encrypted:
            return None
        return decrypt_secret(record.api_key_encrypted)

    def to_public_dict(self, record: AIModelConfig) -> dict[str, object]:
        return {
            "id": record.id,
            "name": record.name,
            "provider": record.provider,
            "base_url": record.base_url,
            "masked_api_key": mask_api_key(self.decrypt_api_key(record)),
            "model_name": record.model_name,
            "temperature": record.temperature,
            "max_tokens": record.max_tokens,
            "timeout_seconds": record.timeout_seconds,
            "is_default": record.is_default,
            "enabled": record.enabled,
            "purpose": record.purpose,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _clear_default(self, *, except_id: int | None = None) -> None:
        for record in self.session.scalars(select(AIModelConfig).where(AIModelConfig.is_default.is_(True))):
            if except_id is not None and record.id == except_id:
                continue
            record.is_default = False

    def _validate_choice(self, values: dict[str, Any]) -> None:
        provider = values.get("provider")
        if provider is not None and provider not in ALLOWED_PROVIDERS:
            raise ValueError(f"Unsupported provider: {provider}")
        purpose = values.get("purpose")
        if purpose is not None and purpose not in ALLOWED_PURPOSES:
            raise ValueError(f"Unsupported purpose: {purpose}")

    def _validate_agent_key(self, agent_key: str) -> None:
        if agent_key not in ALLOWED_AGENT_KEYS:
            raise ValueError(f"Unsupported AI agent: {agent_key}")


def mask_api_key(api_key: str | None) -> str | None:
    return mask_tail(api_key, prefix_length=3, tail_length=4)
