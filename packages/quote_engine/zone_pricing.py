from dataclasses import dataclass
from decimal import Decimal
from math import ceil

from packages.quote_engine.pricing import money
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_models import AddressType


@dataclass(frozen=True)
class ZonePricingResult:
    fuel_usd: Decimal
    accessorials: dict[str, Decimal]
    total_price_usd: Decimal


def calculate_zone_price(
    *,
    base_price_usd: Decimal,
    address_type: AddressType,
    requires_liftgate: bool = False,
    requires_pallet_jack: bool = False,
    requires_appointment: bool = False,
    detention_minutes: int = 0,
    config: ZonePricingConfig | None = None,
) -> ZonePricingResult:
    pricing_config = config or ZonePricingConfig()
    fuel_usd = money(base_price_usd * pricing_config.fuel_percent / Decimal("100"))
    accessorials: dict[str, Decimal] = {}

    if address_type in {AddressType.RESIDENTIAL, AddressType.PRIVATE, AddressType.RURAL_RESIDENTIAL}:
        accessorials["residential_fee_usd"] = pricing_config.residential_fee_usd
    if requires_liftgate:
        accessorials["liftgate_fee_usd"] = pricing_config.liftgate_fee_usd
    if requires_pallet_jack:
        accessorials["pallet_jack_fee_usd"] = pricing_config.pallet_jack_fee_usd
    if requires_appointment:
        accessorials["appointment_fee_usd"] = pricing_config.appointment_fee_usd

    billable_detention_minutes = max(0, detention_minutes - pricing_config.detention_free_minutes)
    if billable_detention_minutes:
        half_hours = ceil(billable_detention_minutes / 30)
        accessorials["detention_fee_usd"] = money(pricing_config.detention_half_hour_fee_usd * half_hours)

    total = money(base_price_usd + fuel_usd + sum(accessorials.values(), Decimal("0")))
    return ZonePricingResult(
        fuel_usd=fuel_usd,
        accessorials={key: money(value) for key, value in accessorials.items()},
        total_price_usd=total,
    )
