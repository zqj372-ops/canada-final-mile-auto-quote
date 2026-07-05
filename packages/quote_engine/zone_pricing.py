from dataclasses import dataclass
from decimal import Decimal
from math import ceil

from packages.quote_engine.pricing import money
from packages.quote_engine.zone_models import AddressType


FUEL_PERCENT = Decimal("35")
RESIDENTIAL_FEE_USD = Decimal("50")
LIFTGATE_FEE_USD = Decimal("50")
PALLET_JACK_FEE_USD = Decimal("50")
APPOINTMENT_FEE_USD = Decimal("50")
DETENTION_HALF_HOUR_FEE_USD = Decimal("35")


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
) -> ZonePricingResult:
    fuel_usd = money(base_price_usd * FUEL_PERCENT / Decimal("100"))
    accessorials: dict[str, Decimal] = {}

    if address_type in {AddressType.RESIDENTIAL, AddressType.PRIVATE, AddressType.RURAL_RESIDENTIAL}:
        accessorials["residential_fee_usd"] = RESIDENTIAL_FEE_USD
    if requires_liftgate:
        accessorials["liftgate_fee_usd"] = LIFTGATE_FEE_USD
    if requires_pallet_jack:
        accessorials["pallet_jack_fee_usd"] = PALLET_JACK_FEE_USD
    if requires_appointment:
        accessorials["appointment_fee_usd"] = APPOINTMENT_FEE_USD

    billable_detention_minutes = max(0, detention_minutes - 30)
    if billable_detention_minutes:
        half_hours = ceil(billable_detention_minutes / 30)
        accessorials["detention_fee_usd"] = money(DETENTION_HALF_HOUR_FEE_USD * half_hours)

    total = money(base_price_usd + fuel_usd + sum(accessorials.values(), Decimal("0")))
    return ZonePricingResult(
        fuel_usd=fuel_usd,
        accessorials={key: money(value) for key, value in accessorials.items()},
        total_price_usd=total,
    )

