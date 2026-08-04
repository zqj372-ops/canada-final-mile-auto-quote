from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import FCLQuoteConfigVersion, FCLRateCard, QuoteRuleConfig
from packages.quote_engine.fcl import (
    FCLQuoteConfig,
    FCLRateCardPayload,
    default_fcl_quote_config,
)


FCL_CONFIG_DRAFT_KEY = "fcl_quote_config_draft"
FCL_CONFIG_PUBLISHED_KEY = "fcl_quote_config_published"
FCL_CONFIG_VERSION_KEY = "fcl_quote_config_version"


class FCLQuoteConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_draft(self) -> FCLQuoteConfig:
        return self._get_config(FCL_CONFIG_DRAFT_KEY) or default_fcl_quote_config()

    def get_published(self) -> tuple[FCLQuoteConfig | None, int]:
        config = self._get_config(FCL_CONFIG_PUBLISHED_KEY)
        version_row = self.session.get(QuoteRuleConfig, FCL_CONFIG_VERSION_KEY)
        try:
            version = int(version_row.value) if version_row else 0
        except (TypeError, ValueError):
            version = 0
        return config, version

    def admin_snapshot(self) -> dict[str, object]:
        published, version = self.get_published()
        return {
            "draft": self.get_draft().model_dump(mode="json"),
            "published": published.model_dump(mode="json") if published else None,
            "published_version": version,
        }

    def save_draft(self, config: FCLQuoteConfig) -> FCLQuoteConfig:
        self._save_json(FCL_CONFIG_DRAFT_KEY, config.model_dump(mode="json"), "FCL quote draft configuration")
        self.session.commit()
        return config

    def publish_draft(self, actor: CurrentActor) -> tuple[FCLQuoteConfig, int]:
        config = self.get_draft()
        self._validate_config(config)
        latest = self.session.scalar(select(func.max(FCLQuoteConfigVersion.version))) or 0
        version = int(latest) + 1
        config_json = config.model_dump(mode="json")
        self._save_json(FCL_CONFIG_PUBLISHED_KEY, config_json, "FCL published configuration")
        self._save_json(FCL_CONFIG_VERSION_KEY, str(version), "FCL published configuration version")
        self.session.add(
            FCLQuoteConfigVersion(
                version=version,
                config_json=config_json,
                published_by=actor.name,
                published_at=datetime.now(UTC),
            )
        )
        self.session.commit()
        return config, version

    def validate_draft(self) -> list[str]:
        try:
            self._validate_config(self.get_draft())
        except ValueError as exc:
            return [str(exc)]
        return []

    def list_rate_cards(self, *, status: str | None = None) -> list[FCLRateCard]:
        query = select(FCLRateCard).order_by(FCLRateCard.updated_at.desc(), FCLRateCard.id.desc())
        if status:
            query = query.where(FCLRateCard.status == status)
        return list(self.session.scalars(query))

    def create_rate_card(self, payload: FCLRateCardPayload) -> FCLRateCard:
        self._validate_rate_card_dates(payload)
        record = FCLRateCard(
            **payload.model_dump(exclude={"fee_lines"}),
            status="draft",
            fee_lines=[line.model_dump(mode="json") for line in payload.fee_lines],
        )
        self.session.add(record)
        self.session.commit()
        self.session.refresh(record)
        return record

    def update_rate_card(self, record_id: int, payload: FCLRateCardPayload) -> FCLRateCard:
        record = self.session.get(FCLRateCard, record_id)
        if record is None:
            raise LookupError("FCL rate card not found.")
        if record.status == "published":
            raise ValueError("Published FCL rate cards are immutable; create a new draft instead.")
        self._validate_rate_card_dates(payload)
        for key, value in payload.model_dump(exclude={"fee_lines"}).items():
            setattr(record, key, value)
        record.fee_lines = [line.model_dump(mode="json") for line in payload.fee_lines]
        record.status = "draft"
        self.session.commit()
        self.session.refresh(record)
        return record

    def publish_rate_card(self, record_id: int) -> FCLRateCard:
        record = self.session.get(FCLRateCard, record_id)
        if record is None:
            raise LookupError("FCL rate card not found.")
        payload = self._payload_from_record(record)
        self._validate_rate_card_dates(payload)
        record.status = "published"
        self.session.commit()
        self.session.refresh(record)
        return record

    def to_dict(self, record: FCLRateCard) -> dict[str, object]:
        payload = self._payload_from_record(record)
        return {
            "id": record.id,
            **payload.model_dump(mode="json"),
            "status": record.status,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        }

    def _payload_from_record(self, record: FCLRateCard) -> FCLRateCardPayload:
        return FCLRateCardPayload.model_validate(
            {
                "pol": record.pol,
                "pod": record.pod,
                "container_type": record.container_type,
                "carrier": record.carrier,
                "service": record.service,
                "service_scope": record.service_scope,
                "effective_from": record.effective_from,
                "effective_to": record.effective_to,
                "etd_date": record.etd_date,
                "vessel_voyage": record.vessel_voyage,
                "priority": record.priority,
                "source": record.source,
                "enabled": record.enabled,
                "fee_lines": record.fee_lines,
            }
        )

    def _get_config(self, key: str) -> FCLQuoteConfig | None:
        record = self.session.get(QuoteRuleConfig, key)
        if record is None:
            return None
        try:
            value: Any = json.loads(record.value)
            return FCLQuoteConfig.model_validate(value)
        except (json.JSONDecodeError, TypeError, ValueError):
            return None

    def _save_json(self, key: str, value: object, description: str) -> None:
        record = self.session.get(QuoteRuleConfig, key)
        serialized = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        if record is None:
            self.session.add(QuoteRuleConfig(key=key, value=serialized, description=description))
        else:
            record.value = serialized
            record.description = description

    @staticmethod
    def _validate_config(config: FCLQuoteConfig) -> None:
        if config.settlement_currency and not config.exchange_rates and any(config.required_fields):
            raise ValueError("settlement_currency requires at least one valid exchange rate snapshot")
        for rate in config.exchange_rates:
            if rate.effective_from and rate.effective_to and rate.effective_from > rate.effective_to:
                raise ValueError("exchange rate effective_from must be before effective_to")

    @staticmethod
    def _validate_rate_card_dates(payload: FCLRateCardPayload) -> None:
        if payload.effective_from and payload.effective_to and payload.effective_from > payload.effective_to:
            raise ValueError("rate card effective_from must be before effective_to")

