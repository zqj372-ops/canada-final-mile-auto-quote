"""Published-rule configuration for the NA oversize pallet calculator (v2).

v2 follows the redesigned billing model (2026-08-07 design spec): billing
pallets are the max of pallet-position rows, volume pallets (ceil CBM/2),
weight pallets (ceil kg/500), overlength pieces (each 2 pallets), wooden
crates (>=1 pallet each) and a validated explicit pallet count.

The model is intentionally lenient (``extra="ignore"``) so snapshots
published under the deprecated TEMP_V1 schema keep parsing; unknown legacy
fields are ignored and v2 defaults apply.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class VehicleProfile(BaseModel):
    """Effective dimensions and capacity limits for one vehicle type.

    Vehicle profiles are pure data used only for a conservative capacity
    reference (design v2 section 5).  They never gate automatic quoting.
    """

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    code: str = Field(min_length=1, validation_alias=AliasChoices("code", "vehicle_code"))
    label: str = Field(min_length=1)
    length_cm: Decimal = Field(gt=0)
    width_cm: Decimal = Field(gt=0)
    height_cm: Decimal = Field(gt=0)
    volume_cbm: Decimal = Field(gt=0)
    payload_kg: Decimal = Field(gt=0)
    common_pallet_limit: int = Field(ge=1)
    tight_pallet_limit: int = Field(ge=1)
    comparable_base_price: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_pallet_limit_order(self) -> "VehicleProfile":
        if self.common_pallet_limit > self.tight_pallet_limit:
            raise ValueError("common_pallet_limit must be less than or equal to tight_pallet_limit")
        return self


class FlexiblePackageDeal(BaseModel):
    """Flat-rate mode for woven/flexible packaging (design v2 section 2.8)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    keywords: list[str] = Field(
        default_factory=lambda: ["编织袋", "柔性包装", "woven bag", "flexible packaging"]
    )
    min_pieces: int = Field(default=50, ge=1)
    requires_stackable: bool = True
    quote_usd_per_container: Decimal = Field(default=Decimal("580"), ge=0)


class OversizePalletRuleConfig(BaseModel):
    """All tunable inputs used by oversize pallet calculations (v2)."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        # Legacy TEMP_V1 snapshots carry fields this model no longer defines;
        # they are ignored so an old published seed still parses with v2 defaults.
        extra="ignore",
        validate_assignment=True,
    )

    rule_id: str = Field(default="NA_OVERSIZE_RULE_V2", min_length=1)

    # Pallet position (48x40 GMA standard)
    standard_pallet_length_cm: Decimal = Field(
        default=Decimal("121.92"), gt=0,
        validation_alias=AliasChoices("standard_pallet_length_cm", "standard_pallet_long_cm"),
    )
    standard_pallet_width_cm: Decimal = Field(
        default=Decimal("101.60"), gt=0,
        validation_alias=AliasChoices("standard_pallet_width_cm", "standard_pallet_short_cm"),
    )
    standard_pallet_area_cm2: Decimal = Field(default=Decimal("12387.072"), gt=0)
    pallet_area_tolerance_ratio: Decimal = Field(default=Decimal("0"), ge=0, le=1)

    # Volume / weight equivalents (validated against 493 historical orders)
    volume_cbm_per_pallet: Decimal = Field(
        default=Decimal("2"), gt=0,
        validation_alias=AliasChoices("volume_cbm_per_pallet", "cbm_per_pallet"),
    )
    weight_kg_per_pallet: Decimal = Field(
        default=Decimal("500"), gt=0,
        validation_alias=AliasChoices("weight_kg_per_pallet", "kg_per_pallet"),
    )

    # Overlength pieces (carrier rule: >120cm single piece bills 2 pallets)
    long_piece_threshold_cm: Decimal = Field(
        default=Decimal("120"), gt=0,
        validation_alias=AliasChoices("long_piece_threshold_cm", "long_piece_threshold"),
    )
    long_piece_pallets_per_piece: int = Field(default=2, ge=1)

    # Wooden crates (>=1 pallet each; overlength crates 2)
    wooden_crate_min_pallets_per_piece: int = Field(default=1, ge=1)
    wooden_crate_long_pallets_per_piece: int = Field(default=2, ge=1)

    # Explicit pallet count cross-check
    explicit_pallet_tolerance_ratio: Decimal = Field(default=Decimal("0.5"), ge=0, le=5)

    # Mechanical handling limit (above -> manual)
    mechanical_handling_weight_limit_kg: Decimal = Field(default=Decimal("1000"), gt=0)

    # Density / DIM (risk-only by default; DIM adjustment is opt-in)
    low_density_threshold_lb_per_cuft: Decimal = Field(default=Decimal("4"), gt=0)
    dim_pallet_adjustment_enabled: bool = False
    dim_factor: Decimal = Field(default=Decimal("194"), gt=0)

    # Flat-rate flexible package deal (design v2 section 2.8)
    flexible_package_deal: FlexiblePackageDeal | None = Field(
        default_factory=lambda: FlexiblePackageDeal()
    )

    # Aggregate-quote fallback tier (design v2 section 6.1)
    aggregate_quote_enabled: bool = True

    # Reconciliation tolerances
    customer_piece_tolerance_absolute: int = Field(default=2, ge=0)
    customer_piece_tolerance_ratio: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    weight_tolerance_absolute_kg: Decimal = Field(default=Decimal("50"), ge=0)
    weight_tolerance_ratio: Decimal = Field(default=Decimal("0.05"), ge=0, le=1)
    volume_tolerance_absolute_cbm: Decimal = Field(default=Decimal("0.5"), ge=0)
    volume_tolerance_ratio: Decimal = Field(default=Decimal("0.10"), ge=0, le=1)

    # Vehicle profiles (conservative capacity reference only; pure data)
    vehicle_profiles: list[VehicleProfile] = Field(
        default_factory=lambda: _default_vehicle_profiles(),
        validation_alias=AliasChoices("vehicle_profiles", "vehicles"),
    )

    @model_validator(mode="after")
    def validate_rule_order_and_vehicles(self) -> "OversizePalletRuleConfig":
        if self.standard_pallet_area_cm2 != (
            self.standard_pallet_length_cm * self.standard_pallet_width_cm
        ):
            raise ValueError("standard_pallet_area_cm2 must equal pallet length multiplied by width")
        codes = [profile.code for profile in self.vehicle_profiles]
        if len(codes) != len(set(codes)):
            raise ValueError("vehicle profile codes must be unique")
        return self


def _default_vehicle_profiles() -> list[VehicleProfile]:
    return [
        VehicleProfile(
            code="26_non_cdl",
            label="26尺非CDL",
            length_cm=Decimal("762"),
            width_cm=Decimal("243.84"),
            height_cm=Decimal("243.84"),
            volume_cbm=Decimal("45.3"),
            payload_kg=Decimal("4536"),
            common_pallet_limit=12,
            tight_pallet_limit=14,
        ),
        VehicleProfile(
            code="26_cdl",
            label="26尺CDL",
            length_cm=Decimal("762"),
            width_cm=Decimal("243.84"),
            height_cm=Decimal("243.84"),
            volume_cbm=Decimal("45.3"),
            payload_kg=Decimal("7711"),
            common_pallet_limit=12,
            tight_pallet_limit=14,
        ),
        VehicleProfile(
            code="53_dry_van",
            label="53尺干货车",
            length_cm=Decimal("1600.2"),
            width_cm=Decimal("250.19"),
            height_cm=Decimal("279.4"),
            volume_cbm=Decimal("110.4"),
            payload_kg=Decimal("19958"),
            common_pallet_limit=26,
            tight_pallet_limit=30,
        ),
    ]


def _build_default_rule() -> OversizePalletRuleConfig:
    return OversizePalletRuleConfig(vehicle_profiles=_default_vehicle_profiles())


_DEFAULT_OVERSIZE_PALLET_RULE = _build_default_rule()


def default_oversize_pallet_rule() -> OversizePalletRuleConfig:
    """Return a deep, independently mutable copy of the published defaults."""

    return deepcopy(_DEFAULT_OVERSIZE_PALLET_RULE)


__all__ = [
    "FlexiblePackageDeal",
    "OversizePalletRuleConfig",
    "VehicleProfile",
    "default_oversize_pallet_rule",
]
