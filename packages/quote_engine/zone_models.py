from dataclasses import dataclass, field
from decimal import Decimal
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.address_normalizer import normalize_city, normalize_postal_code, normalize_province


class ZoneQuoteSourceType(StrEnum):
    ZONE_MATRIX = "zone_matrix"
    HERMES_AGENT_CORRECTION = "hermes_agent_correction"
    LEARNED_MANUAL_QUOTE = "learned_manual_quote"
    MANUAL_REQUIRED = "manual_required"


class AddressType(StrEnum):
    COMMERCIAL = "commercial"
    RESIDENTIAL = "residential"
    PRIVATE = "private"
    RURAL_RESIDENTIAL = "rural_residential"


class ZoneQuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address_line: str | None = None
    postal_code: str
    city: str | None = None
    province: str | None = None
    cbm: Decimal = Field(ge=0)
    weight_kg: Decimal = Field(ge=0)
    piece_count: int = Field(ge=1)
    packaging_type: str
    longest_side_cm: Decimal | None = Field(default=None, ge=0)
    address_type: AddressType
    requires_liftgate: bool = False
    requires_pallet_jack: bool = False
    requires_appointment: bool = False
    explicit_pallet_count: int | None = Field(default=None, ge=1)
    is_stackable: bool | None = None
    detention_minutes: int = Field(default=0, ge=0)

    @field_validator("postal_code")
    @classmethod
    def normalize_postal(cls, value: str) -> str:
        normalized = normalize_postal_code(value)
        if normalized is None:
            raise ValueError("postal_code must be a valid Canadian postal code")
        return normalized

    @field_validator("city")
    @classmethod
    def normalize_city_value(cls, value: str | None) -> str | None:
        return normalize_city(value)

    @field_validator("province")
    @classmethod
    def normalize_province_value(cls, value: str | None) -> str | None:
        return normalize_province(value)

    @field_validator("packaging_type")
    @classmethod
    def normalize_packaging_type(cls, value: str) -> str:
        return value.strip().lower()


class ZoneQuoteResult(BaseModel):
    quote_id: str = Field(default_factory=lambda: str(uuid4()))
    source_type: ZoneQuoteSourceType
    confidence: int = Field(ge=0, le=100)
    postal_code: str | None = None
    preferred_city: str | None = None
    postal_prefix: str | None = None
    city: str | None = None
    province: str | None = None
    origin: str | None = None
    zone: int | None = None
    billing_pallets: int | None = None
    pallet_breakdown: dict[str, int] = Field(default_factory=dict)
    base_price_usd: Decimal | None = None
    fuel_usd: Decimal | None = None
    accessorials: dict[str, Decimal] = Field(default_factory=dict)
    total_price_usd: Decimal | None = None
    risk_tags: list[str] = Field(default_factory=list)
    manual_review_required: bool
    matched_rule: str
    matched_by: str | None = None
    candidate_count: int = 0
    match_trace: dict[str, object] = Field(default_factory=dict)
    sales_note: str | None = None
    internal_note: str | None = None


@dataclass(frozen=True)
class PostalCodeCityRecord:
    postal_code: str
    preferred_city: str
    province: str | None = None
    fsa: str | None = None
    official_city: str | None = None
    municipality: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    source: str | None = None


@dataclass(frozen=True)
class PostalZoneOverrideRecord:
    postal_code: str
    postal_prefix: str
    province: str
    canonical_city: str | None
    origin: str
    zone: int
    confidence: int = 100
    source: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class CityAliasRecord:
    province: str
    alias_city: str
    canonical_city: str
    alias_type: str | None = None


@dataclass(frozen=True)
class ZoneLookupRuleRecord:
    postal_prefix: str
    city: str
    province: str
    origin: str
    zone: int
    canonical_city: str | None = None
    priority: int = 100
    active: bool = True
    match_level: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class ZonePriceRecord:
    origin: str
    zone: int
    billing_pallets: int
    base_price_usd: Decimal
    source: str | None = None
    last_updated: str | None = None


@dataclass(frozen=True)
class ZoneLookupDecision:
    manual_required: bool
    matched_rule: str
    rule: ZoneLookupRuleRecord | None = None
    origin: str | None = None
    zone: int | None = None
    confidence: int = 0
    risk_tags: tuple[str, ...] = ()
    matched_by: str | None = None
    candidate_count: int = 0
    match_trace: dict[str, object] = field(default_factory=dict)
