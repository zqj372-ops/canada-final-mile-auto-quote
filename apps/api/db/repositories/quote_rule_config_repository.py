import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import QuoteRuleConfig
from packages.quote_engine.workbench_config import QuoteWorkbenchConfig
from packages.quote_engine.zone_config import ZonePricingConfig


WORKBENCH_CONFIG_KEY = "quote_workbench_config"

DECIMAL_KEYS = {
    "fuel_percent",
    "residential_fee_usd",
    "liftgate_fee_usd",
    "pallet_jack_fee_usd",
    "appointment_fee_usd",
    "detention_half_hour_fee_usd",
}


class QuoteRuleConfigRepository:
    def __init__(self, session: Session):
        self.session = session

    def get_workbench_config(self) -> QuoteWorkbenchConfig:
        record = self.session.get(QuoteRuleConfig, WORKBENCH_CONFIG_KEY)
        if record is None:
            return QuoteWorkbenchConfig()

        try:
            data = json.loads(record.value)
        except json.JSONDecodeError:
            return QuoteWorkbenchConfig()

        try:
            return QuoteWorkbenchConfig.model_validate(data)
        except ValueError:
            return QuoteWorkbenchConfig()

    def save_workbench_config(self, config: QuoteWorkbenchConfig) -> QuoteWorkbenchConfig:
        value = config.model_dump_json()
        record = self.session.get(QuoteRuleConfig, WORKBENCH_CONFIG_KEY)
        if record is None:
            record = QuoteRuleConfig(
                key=WORKBENCH_CONFIG_KEY,
                value=value,
                description="Backend-owned configuration for the Chinese AI quote workbench.",
            )
            self.session.add(record)
        else:
            record.value = value
        self.session.commit()
        self.session.refresh(record)
        return config

    def get_zone_pricing_config(self) -> ZonePricingConfig:
        defaults = ZonePricingConfig()
        records = self.session.scalars(select(QuoteRuleConfig)).all()
        values: dict[str, object] = {}
        valid_keys = set(ZonePricingConfig.model_fields)

        for record in records:
            if record.key not in valid_keys:
                continue
            parsed = self._parse_value(record.key, record.value)
            if parsed is not None:
                values[record.key] = parsed

        return defaults.model_copy(update=values)

    def save_zone_pricing_config(self, config: ZonePricingConfig) -> ZonePricingConfig:
        descriptions = {
            "fuel_percent": "Fuel surcharge percent applied to zone base price.",
            "residential_fee_usd": "Residential delivery accessorial fee.",
            "liftgate_fee_usd": "Liftgate accessorial fee.",
            "pallet_jack_fee_usd": "Pallet jack accessorial fee.",
            "appointment_fee_usd": "Appointment delivery accessorial fee.",
            "detention_half_hour_fee_usd": "Detention fee per billable half hour.",
            "detention_free_minutes": "Free detention minutes before billing starts.",
        }
        for key, value in config.model_dump().items():
            record = self.session.get(QuoteRuleConfig, key)
            string_value = str(value)
            if record is None:
                record = QuoteRuleConfig(
                    key=key,
                    value=string_value,
                    description=descriptions.get(key),
                )
                self.session.add(record)
            else:
                record.value = string_value
                record.description = record.description or descriptions.get(key)
        self.session.commit()
        return config

    def _parse_value(self, key: str, value: str) -> Decimal | int | None:
        try:
            if key in DECIMAL_KEYS:
                return Decimal(value)
            if key == "detention_free_minutes":
                return int(value)
        except (InvalidOperation, ValueError):
            return None
        return None
