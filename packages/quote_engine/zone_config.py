from decimal import Decimal

from pydantic import BaseModel, Field


class ZonePricingConfig(BaseModel):
    fuel_percent: Decimal = Field(default=Decimal("35"), ge=0)
    residential_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    liftgate_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    pallet_jack_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    appointment_fee_usd: Decimal = Field(default=Decimal("50"), ge=0)
    detention_half_hour_fee_usd: Decimal = Field(default=Decimal("35"), ge=0)
    detention_free_minutes: int = Field(default=30, ge=0)
