import json
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import QuoteRuleConfig
from packages.quote_engine.workbench_config import QuoteWorkbenchConfig
from packages.quote_engine.zone_config import ZonePricingConfig


WORKBENCH_CONFIG_KEY = "quote_workbench_config"
ZONE_FUEL_PERCENT_KEY = "fuel_percent_by_zone"
ZONE_PRICE_ENABLED_KEY = "zone_price_enabled_by_zone"
JSON_OBJECT_KEYS = {ZONE_FUEL_PERCENT_KEY, ZONE_PRICE_ENABLED_KEY}
INVALID_CONFIG_VALUE = object()

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
        zone_pricing = self.get_zone_pricing_config()
        record = self.session.get(QuoteRuleConfig, WORKBENCH_CONFIG_KEY)
        if record is None:
            return QuoteWorkbenchConfig(zone_pricing=zone_pricing)

        try:
            data = json.loads(record.value)
        except json.JSONDecodeError:
            return QuoteWorkbenchConfig(zone_pricing=zone_pricing)

        try:
            config = QuoteWorkbenchConfig.model_validate(data)
        except ValueError:
            return QuoteWorkbenchConfig(zone_pricing=zone_pricing)
        return config.model_copy(update={"zone_pricing": zone_pricing})

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
        self._upsert_zone_pricing_records(config.zone_pricing)
        self.session.commit()
        self.session.refresh(record)
        return config

    def get_zone_pricing_config(self) -> ZonePricingConfig:
        config = self._get_standalone_zone_pricing_config()
        record = self.session.get(QuoteRuleConfig, WORKBENCH_CONFIG_KEY)
        if record is None:
            return config

        try:
            data = json.loads(record.value)
        except json.JSONDecodeError:
            return config
        workbench_pricing = data.get("zone_pricing") if isinstance(data, dict) else None
        if not isinstance(workbench_pricing, dict):
            return config

        try:
            return ZonePricingConfig.model_validate({**config.model_dump(), **workbench_pricing})
        except ValueError:
            return config

    def _get_standalone_zone_pricing_config(self) -> ZonePricingConfig:
        defaults = ZonePricingConfig()
        values: dict[str, object] = {}
        valid_keys = set(ZonePricingConfig.model_fields)

        for record in self.session.scalars(
            select(QuoteRuleConfig).execution_options(stream_results=True, yield_per=5000)
        ):
            if record.key not in valid_keys:
                continue
            parsed = self._parse_value(record.key, record.value)
            if parsed is not INVALID_CONFIG_VALUE:
                values[record.key] = parsed

        try:
            return ZonePricingConfig.model_validate({**defaults.model_dump(), **values})
        except ValueError:
            return defaults

    def save_zone_pricing_config(self, config: ZonePricingConfig) -> ZonePricingConfig:
        self._upsert_zone_pricing_records(config)
        self._sync_workbench_zone_pricing(config)
        self.session.commit()
        return config

    def _upsert_zone_pricing_records(self, config: ZonePricingConfig) -> None:
        descriptions = {
            "fuel_percent": "Fuel surcharge percent applied to zone base price.",
            ZONE_FUEL_PERCENT_KEY: "Fuel surcharge percent overrides keyed by origin and zone.",
            "zone_price_enabled": "Global switch for automatic Zone price quotes.",
            "max_auto_quote_zone": "Default highest Zone eligible for automatic quotes.",
            ZONE_PRICE_ENABLED_KEY: "Zone price availability switches keyed by origin and zone.",
            "residential_fee_usd": "Residential delivery accessorial fee.",
            "liftgate_fee_usd": "Liftgate accessorial fee.",
            "pallet_jack_fee_usd": "Pallet jack accessorial fee.",
            "appointment_fee_usd": "Appointment delivery accessorial fee.",
            "detention_half_hour_fee_usd": "Detention fee per billable half hour.",
            "detention_free_minutes": "Free detention minutes before billing starts.",
        }
        for key, value in config.model_dump(mode="json").items():
            record = self.session.get(QuoteRuleConfig, key)
            string_value = json.dumps(value, sort_keys=True) if key in JSON_OBJECT_KEYS else str(value)
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

    def _sync_workbench_zone_pricing(self, config: ZonePricingConfig) -> None:
        record = self.session.get(QuoteRuleConfig, WORKBENCH_CONFIG_KEY)
        if record is None:
            return
        try:
            data = json.loads(record.value)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict):
            return
        data["zone_pricing"] = config.model_dump(mode="json")
        record.value = json.dumps(data, ensure_ascii=False, sort_keys=True)

    def _parse_value(
        self,
        key: str,
        value: str,
    ) -> Decimal | int | bool | dict[str, Decimal] | dict[str, bool] | None | object:
        try:
            if key in DECIMAL_KEYS:
                return Decimal(value)
            if key == ZONE_FUEL_PERCENT_KEY:
                parsed = json.loads(value)
                if not isinstance(parsed, dict):
                    return INVALID_CONFIG_VALUE
                result = {str(zone_key): Decimal(str(percent)) for zone_key, percent in parsed.items()}
                return result if all(percent >= 0 for percent in result.values()) else INVALID_CONFIG_VALUE
            if key == ZONE_PRICE_ENABLED_KEY:
                parsed = json.loads(value)
                if not isinstance(parsed, dict) or not all(isinstance(enabled, bool) for enabled in parsed.values()):
                    return INVALID_CONFIG_VALUE
                return {str(zone_key): enabled for zone_key, enabled in parsed.items()}
            if key == "detention_free_minutes":
                return int(value)
            if key == "max_auto_quote_zone":
                if value.strip().lower() in {"", "none", "null"}:
                    return None
                return int(value)
            if key == "zone_price_enabled":
                normalized = value.strip().lower()
                if normalized in {"1", "true", "yes", "on", "enabled"}:
                    return True
                if normalized in {"0", "false", "no", "off", "disabled"}:
                    return False
        except (InvalidOperation, TypeError, ValueError):
            return INVALID_CONFIG_VALUE
        return INVALID_CONFIG_VALUE
