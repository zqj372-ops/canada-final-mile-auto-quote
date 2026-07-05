from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.address_normalizer import normalize_city, normalize_postal_code, normalize_province


class SourceType(StrEnum):
    HISTORY_EXACT_ADDRESS = "history_exact_address"
    POSTAL_CODE = "postal_code"
    FSA = "fsa"
    CITY = "city"
    RATE_CARD = "rate_card"
    DISTANCE_FALLBACK = "distance_fallback"
    MANUAL_REQUIRED = "manual_required"


class ShipmentInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    province: str | None = None
    origin_warehouse: str | None = None
    pallet_count: int = Field(ge=1)
    weight_kg: Decimal | None = Field(default=None, ge=0)
    is_residential: bool | None = None
    dock_available: bool | None = None
    requires_appointment: bool = False
    requires_liftgate: bool = False
    limited_access: bool = False
    remote_area: bool = False
    target_margin_percent: Decimal = Field(default=Decimal("0.25"), ge=0, lt=1)

    @field_validator("postal_code")
    @classmethod
    def normalize_postal(cls, value: str | None) -> str | None:
        return normalize_postal_code(value)

    @field_validator("city")
    @classmethod
    def normalize_city_value(cls, value: str | None) -> str | None:
        return normalize_city(value)

    @field_validator("province")
    @classmethod
    def normalize_province_value(cls, value: str | None) -> str | None:
        return normalize_province(value)


class RateRule(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    rule_id: str
    source_type: SourceType
    origin_warehouse: str | None = None
    vendor_name: str | None = None
    province: str | None = None
    city: str | None = None
    fsa: str | None = None
    postal_code: str | None = None
    address_fingerprint: str | None = None
    pallet_min: int = Field(ge=1)
    pallet_max: int = Field(ge=1)
    weight_min_kg: Decimal | None = Field(default=None, ge=0)
    weight_max_kg: Decimal | None = Field(default=None, ge=0)
    base_cost_cad: Decimal = Field(ge=0)
    fuel_percent: Decimal = Field(default=Decimal("0"), ge=0)
    appointment_fee_cad: Decimal = Field(default=Decimal("0"), ge=0)
    liftgate_fee_cad: Decimal = Field(default=Decimal("0"), ge=0)
    residential_fee_cad: Decimal = Field(default=Decimal("0"), ge=0)
    limited_access_fee_cad: Decimal = Field(default=Decimal("0"), ge=0)
    remote_fee_cad: Decimal = Field(default=Decimal("0"), ge=0)
    effective_from: date | None = None
    effective_to: date | None = None
    status: str = "active"

    @field_validator("postal_code")
    @classmethod
    def normalize_postal(cls, value: str | None) -> str | None:
        return normalize_postal_code(value)

    @field_validator("city")
    @classmethod
    def normalize_city_value(cls, value: str | None) -> str | None:
        return normalize_city(value)

    @field_validator("province")
    @classmethod
    def normalize_province_value(cls, value: str | None) -> str | None:
        return normalize_province(value)

    @field_validator("fsa")
    @classmethod
    def normalize_fsa(cls, value: str | None) -> str | None:
        return value.upper().replace(" ", "") if value else None


class MatchResult(BaseModel):
    source_type: SourceType
    confidence: int = Field(ge=0, le=100)
    matched_rule: str
    rule: RateRule | None = None


class QuoteResult(BaseModel):
    quote_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: SourceType
    confidence: int = Field(ge=0, le=100)
    matched_rule: str
    internal_cost_cad: Decimal | None = None
    suggested_selling_price_cad: Decimal | None = None
    margin_cad: Decimal | None = None
    margin_percent: Decimal | None = None
    cost_breakdown: dict[str, Decimal] = Field(default_factory=dict)
    risk_tags: list[str] = Field(default_factory=list)
    manual_review_required: bool
    sales_note: str | None = None
    internal_note: str | None = None


class QuoteCalculationRequest(BaseModel):
    shipment: ShipmentInput
    rate_rules: list[RateRule] = Field(default_factory=list)


class AIQuoteContext(BaseModel):
    price_locked: bool = True
    quote_result: dict[str, object]
    allowed_actions: list[str] = Field(default_factory=lambda: ["explain", "summarize", "warn_risk"])
    forbidden_actions: list[str] = Field(
        default_factory=lambda: ["change_price", "invent_fee", "invent_market_rate"]
    )

