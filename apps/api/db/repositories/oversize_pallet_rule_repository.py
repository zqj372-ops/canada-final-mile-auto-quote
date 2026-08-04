"""Persistence and publishing lifecycle for oversize pallet rules."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor
from apps.api.db.models import OversizePalletRuleVersion, QuoteRuleConfig
from packages.quote_engine.oversize_config import (
    OversizePalletRuleConfig,
    default_oversize_pallet_rule,
)


OVERSIZE_PALLET_RULE_DRAFT_KEY = "oversize_pallet_rule_draft"
OVERSIZE_PALLET_RULE_DESCRIPTION = "Oversize pallet rule draft configuration"


class OversizePalletRuleRepository:
    """Store editable drafts separately from immutable published snapshots."""

    def __init__(self, session: Session):
        self.session = session

    def get_draft(self) -> OversizePalletRuleConfig:
        config, _error = self._load_draft()
        return config or default_oversize_pallet_rule()

    def save_draft(
        self,
        config: OversizePalletRuleConfig | Mapping[str, object],
    ) -> OversizePalletRuleConfig:
        validated = self._coerce_config(config)
        self._validate_config(validated)
        config_json = validated.model_dump(mode="json")
        record = self.session.get(QuoteRuleConfig, OVERSIZE_PALLET_RULE_DRAFT_KEY)
        serialized = json.dumps(config_json, ensure_ascii=False, separators=(",", ":"))
        if record is None:
            self.session.add(
                QuoteRuleConfig(
                    key=OVERSIZE_PALLET_RULE_DRAFT_KEY,
                    value=serialized,
                    description=OVERSIZE_PALLET_RULE_DESCRIPTION,
                )
            )
        else:
            record.value = serialized
            record.description = OVERSIZE_PALLET_RULE_DESCRIPTION
        self.session.commit()
        return validated

    def validate_draft(self) -> list[str]:
        config, error = self._load_draft()
        if error:
            return [error]
        if config is None:
            return []
        try:
            self._validate_config(config)
        except ValueError as exc:
            return [str(exc)]
        return []

    def publish_draft(self, actor: CurrentActor) -> tuple[OversizePalletRuleConfig, int]:
        config, error = self._load_draft()
        if error:
            raise ValueError(error)
        config = config or default_oversize_pallet_rule()
        self._validate_config(config)

        latest = self.session.scalar(
            select(func.max(OversizePalletRuleVersion.version)).where(
                OversizePalletRuleVersion.rule_id == config.rule_id
            )
        ) or 0
        version = int(latest) + 1
        config_json = config.model_dump(mode="json")
        self.session.add(
            OversizePalletRuleVersion(
                rule_id=config.rule_id,
                version=version,
                config_json=config_json,
                published_by=actor.name,
                status="published",
            )
        )
        self.session.commit()
        return config, version

    def get_published(
        self,
    ) -> tuple[OversizePalletRuleConfig | Mapping[str, object], int]:
        """Return the current snapshot, preserving invalid rows as a blocker.

        A missing row is the only case that uses the temporary default.  Once a
        published row exists, an invalid JSON snapshot must flow to the quote
        engine as an invalid marker so the calculation becomes manual instead
        of silently quoting with unrelated defaults.
        """
        record = self.session.scalar(
            select(OversizePalletRuleVersion)
            .where(OversizePalletRuleVersion.status == "published")
            .order_by(
                OversizePalletRuleVersion.published_at.desc(),
                OversizePalletRuleVersion.id.desc(),
            )
        )
        if record is None:
            return default_oversize_pallet_rule(), 0
        try:
            config = OversizePalletRuleConfig.model_validate(record.config_json)
        except (TypeError, ValueError):
            return {
                "rule_id": record.rule_id,
                "invalid_reason": "published_snapshot_invalid",
            }, record.version
        return config, record.version

    def admin_snapshot(self) -> dict[str, object]:
        published, version = self.get_published()
        return {
            "draft": self.get_draft().model_dump(mode="json"),
            "published": (
                published.model_dump(mode="json")
                if isinstance(published, OversizePalletRuleConfig)
                else None
            ),
            "published_version": version,
        }

    def _load_draft(self) -> tuple[OversizePalletRuleConfig | None, str | None]:
        record = self.session.get(QuoteRuleConfig, OVERSIZE_PALLET_RULE_DRAFT_KEY)
        if record is None:
            return None, None
        try:
            value: Any = json.loads(record.value)
            return OversizePalletRuleConfig.model_validate(value), None
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            return None, str(exc)

    @staticmethod
    def _coerce_config(
        config: OversizePalletRuleConfig | Mapping[str, object],
    ) -> OversizePalletRuleConfig:
        if isinstance(config, OversizePalletRuleConfig):
            return config
        return OversizePalletRuleConfig.model_validate(config)

    @staticmethod
    def _validate_config(config: OversizePalletRuleConfig) -> None:
        # model_validate/model validators enforce dimensions, vehicle profiles,
        # positive capacity values, and max_auto_vehicles <= 3.  Re-validating
        # here also protects callers that mutate a model between save/publish.
        OversizePalletRuleConfig.model_validate(config.model_dump(mode="python"))


__all__ = [
    "OVERSIZE_PALLET_RULE_DRAFT_KEY",
    "OversizePalletRuleRepository",
]
