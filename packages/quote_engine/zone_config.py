from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field


NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class ZonePricingConfig(BaseModel):
    fuel_percent: Decimal = Field(default=Decimal("35"), ge=0)
    fuel_percent_by_zone: dict[str, NonNegativeDecimal] = Field(default_factory=dict)
    zone_price_enabled: bool = True
    max_auto_quote_zone: int | None = Field(default=7, ge=1)
    zone_price_enabled_by_zone: dict[str, bool] = Field(default_factory=dict)
    residential_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    liftgate_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    pallet_jack_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    appointment_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    detention_half_hour_fee_usd: Decimal = Field(default=Decimal("35"), ge=0)
    detention_free_minutes: int = Field(default=30, ge=0)

    def fuel_percent_for(self, origin: str | None, zone: int | None) -> Decimal:
        if not origin or zone is None:
            return self.fuel_percent
        return self.fuel_percent_by_zone.get(f"{origin.strip().lower()}|{zone}", self.fuel_percent)

    def zone_price_enabled_for(self, origin: str | None, zone: int | None) -> bool:
        if not self.zone_price_enabled or not origin or zone is None:
            return False
        key = f"{origin.strip().lower()}|{zone}"
        if key in self.zone_price_enabled_by_zone:
            return self.zone_price_enabled_by_zone[key]
        return self.max_auto_quote_zone is None or zone <= self.max_auto_quote_zone
