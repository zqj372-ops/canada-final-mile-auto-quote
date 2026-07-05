from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import QuoteRuleConfig
from packages.quote_engine.zone_config import ZonePricingConfig


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

    def _parse_value(self, key: str, value: str) -> Decimal | int | None:
        try:
            if key in DECIMAL_KEYS:
                return Decimal(value)
            if key == "detention_free_minutes":
                return int(value)
        except (InvalidOperation, ValueError):
            return None
        return None
