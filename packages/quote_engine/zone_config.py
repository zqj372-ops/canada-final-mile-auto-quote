from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, Field


NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class ZonePricingConfig(BaseModel):
    fuel_percent: Decimal = Field(default=Decimal("35"), ge=0)
    fuel_percent_by_zone: dict[str, NonNegativeDecimal] = Field(default_factory=dict)
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
