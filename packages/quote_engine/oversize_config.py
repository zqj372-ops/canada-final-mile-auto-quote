"""Published-rule configuration for the NA oversize pallet calculator.

The defaults in this module are an explicitly versioned temporary operating
rule.  They are data, rather than constants hidden in the calculator, so a
later published snapshot can replace them without changing the formulas.
"""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import ClassVar

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator


class VehicleProfile(BaseModel):
    """Effective dimensions and capacity limits for one vehicle type."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    code: str = Field(min_length=1, validation_alias=AliasChoices("code", "vehicle_code"))
    label: str = Field(min_length=1)
    length_cm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("length_cm", "internal_length_cm", "interior_length_cm"),
    )
    width_cm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("width_cm", "internal_width_cm", "interior_width_cm"),
    )
    height_cm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("height_cm", "internal_height_cm", "interior_height_cm"),
    )
    volume_cbm: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("volume_cbm", "effective_volume_cbm", "usable_volume_cbm"),
    )
    payload_kg: Decimal = Field(
        gt=0,
        validation_alias=AliasChoices("payload_kg", "payload_capacity_kg", "max_payload_kg"),
    )
    common_pallet_limit: int = Field(
        ge=1,
        validation_alias=AliasChoices("common_pallet_limit", "common_limit"),
    )
    tight_pallet_limit: int = Field(
        ge=1,
        validation_alias=AliasChoices("tight_pallet_limit", "tight_limit"),
    )
    comparable_base_price: Decimal | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices(
            "comparable_base_price",
            "comparable_base_price_usd",
            "base_price",
        ),
    )

    @model_validator(mode="after")
    def validate_pallet_limit_order(self) -> "VehicleProfile":
        if self.common_pallet_limit > self.tight_pallet_limit:
            raise ValueError("common_pallet_limit must be less than or equal to tight_pallet_limit")
        return self

    # These aliases keep the domain model convenient for callers that use the
    # wording in the design spec while retaining one canonical serialized shape.
    @property
    def internal_length_cm(self) -> Decimal:
        return self.length_cm

    @property
    def internal_width_cm(self) -> Decimal:
        return self.width_cm

    @property
    def internal_height_cm(self) -> Decimal:
        return self.height_cm

    @property
    def effective_volume_cbm(self) -> Decimal:
        return self.volume_cbm

    @property
    def payload_capacity_kg(self) -> Decimal:
        return self.payload_kg


class OversizePalletRuleConfig(BaseModel):
    """All tunable inputs used by oversize pallet and vehicle calculations."""

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
        validate_assignment=True,
    )

    REQUIRED_VEHICLE_CODES: ClassVar[frozenset[str]] = frozenset(
        {"26_non_cdl", "26_cdl", "53_dry_van"}
    )

    rule_id: str = Field(default="NA_OVERSIZE_TEMP_V1", min_length=1)
    standard_pallet_length_cm: Decimal = Field(
        default=Decimal("121.92"),
        gt=0,
        validation_alias=AliasChoices(
            "standard_pallet_length_cm",
            "standard_pallet_long_cm",
            "pallet_length_cm",
            "pallet_long_cm",
        ),
    )
    standard_pallet_width_cm: Decimal = Field(
        default=Decimal("101.60"),
        gt=0,
        validation_alias=AliasChoices(
            "standard_pallet_width_cm",
            "standard_pallet_short_cm",
            "pallet_width_cm",
            "pallet_short_cm",
        ),
    )
    standard_pallet_area_cm2: Decimal = Field(
        default=Decimal("12387.072"),
        gt=0,
        validation_alias=AliasChoices("standard_pallet_area_cm2", "pallet_area_cm2"),
    )
    mild_oversize_length_cm: Decimal = Field(
        default=Decimal("135"),
        gt=0,
        validation_alias=AliasChoices(
            "mild_oversize_length_cm",
            "mild_oversize_long_cm",
            "mild_length_limit_cm",
            "light_oversize_length_cm",
        ),
    )
    mild_oversize_width_cm: Decimal = Field(
        default=Decimal("110"),
        gt=0,
        validation_alias=AliasChoices(
            "mild_oversize_width_cm",
            "mild_oversize_short_cm",
            "mild_width_limit_cm",
            "light_oversize_width_cm",
        ),
    )
    expansion_trigger_length_cm: Decimal = Field(
        default=Decimal("150"),
        gt=0,
        validation_alias=AliasChoices(
            "expansion_trigger_length_cm",
            "long_expansion_trigger_cm",
            "oversize_expansion_length_cm",
        ),
    )
    expansion_trigger_width_cm: Decimal = Field(
        default=Decimal("122"),
        gt=0,
        validation_alias=AliasChoices(
            "expansion_trigger_width_cm",
            "short_expansion_trigger_cm",
            "oversize_expansion_width_cm",
        ),
    )
    expansion_grace_cm: Decimal = Field(
        default=Decimal("5"),
        ge=0,
        validation_alias=AliasChoices(
            "expansion_grace_cm",
            "repeated_boundary_grace_cm",
            "boundary_grace_cm",
        ),
    )
    area_tolerance_ratio: Decimal = Field(
        default=Decimal("0.02"),
        ge=0,
        le=1,
        validation_alias=AliasChoices("area_tolerance_ratio", "area_tolerance"),
    )
    weight_basis_kg: Decimal = Field(
        default=Decimal("500"),
        gt=0,
        validation_alias=AliasChoices(
            "weight_basis_kg",
            "weight_per_pallet_kg",
            "pallet_weight_basis_kg",
        ),
    )
    normal_board_height_cm: Decimal = Field(
        default=Decimal("180"),
        gt=0,
        validation_alias=AliasChoices(
            "normal_board_height_cm",
            "normal_height_limit_cm",
            "normal_height_cm",
        ),
    )
    high_board_height_cm: Decimal = Field(
        default=Decimal("210"),
        gt=0,
        validation_alias=AliasChoices(
            "high_board_height_cm",
            "auto_height_limit_cm",
            "high_height_limit_cm",
        ),
    )
    unit_auto_weight_max_kg: Decimal = Field(
        default=Decimal("1000"),
        gt=0,
        validation_alias=AliasChoices(
            "unit_auto_weight_max_kg",
            "max_unit_weight_kg",
            "max_single_unit_weight_kg",
            "single_unit_auto_weight_max_kg",
        ),
    )
    footprint_surcharge: Decimal = Field(
        default=Decimal("25"),
        ge=0,
        validation_alias=AliasChoices(
            "footprint_surcharge",
            "footprint_surcharge_usd",
            "footprint_fee_usd",
            "footprint_fee",
        ),
    )
    medium_oversize_surcharge: Decimal = Field(
        default=Decimal("50"),
        ge=0,
        validation_alias=AliasChoices(
            "medium_oversize_surcharge",
            "medium_oversize_surcharge_usd",
            "moderate_oversize_surcharge",
            "medium_oversize_fee_usd",
            "medium_oversize_fee",
        ),
    )
    high_board_surcharge: Decimal = Field(
        default=Decimal("50"),
        ge=0,
        validation_alias=AliasChoices(
            "high_board_surcharge",
            "high_board_surcharge_usd",
            "high_board_fee_usd",
            "high_board_fee",
        ),
    )
    heavy_surcharge: Decimal = Field(
        default=Decimal("75"),
        ge=0,
        validation_alias=AliasChoices(
            "heavy_surcharge",
            "heavy_surcharge_usd",
            "heavy_unit_fee_usd",
            "heavy_fee_usd",
            "heavy_fee",
        ),
    )
    customer_piece_tolerance_absolute: int = Field(
        default=2,
        ge=0,
        validation_alias=AliasChoices(
            "customer_piece_tolerance_absolute",
            "customer_piece_tolerance_abs",
            "piece_tolerance_absolute",
        ),
    )
    customer_piece_tolerance_ratio: Decimal = Field(
        default=Decimal("0.05"),
        ge=0,
        le=1,
        validation_alias=AliasChoices("customer_piece_tolerance_ratio", "piece_tolerance_ratio"),
    )
    weight_tolerance_absolute_kg: Decimal = Field(
        default=Decimal("50"),
        ge=0,
        validation_alias=AliasChoices(
            "weight_tolerance_absolute_kg",
            "weight_tolerance_abs_kg",
            "declared_weight_tolerance_kg",
        ),
    )
    weight_tolerance_ratio: Decimal = Field(
        default=Decimal("0.05"),
        ge=0,
        le=1,
        validation_alias=AliasChoices("weight_tolerance_ratio", "declared_weight_tolerance_ratio"),
    )
    volume_tolerance_absolute_cbm: Decimal = Field(
        default=Decimal("0.5"),
        ge=0,
        validation_alias=AliasChoices(
            "volume_tolerance_absolute_cbm",
            "volume_tolerance_abs_cbm",
            "declared_volume_tolerance_cbm",
        ),
    )
    volume_tolerance_ratio: Decimal = Field(
        default=Decimal("0.10"),
        ge=0,
        le=1,
        validation_alias=AliasChoices("volume_tolerance_ratio", "declared_volume_tolerance_ratio"),
    )
    max_auto_vehicles: int = Field(default=3, ge=1, le=3)
    packing_node_limit: int = Field(
        default=10000,
        ge=1,
        validation_alias=AliasChoices(
            "packing_node_limit",
            "deterministic_packing_node_limit",
            "packing_search_node_limit",
            "packing_search_nodes",
            "search_node_limit",
            "max_packing_nodes",
        ),
    )
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
        if self.standard_pallet_length_cm > self.mild_oversize_length_cm:
            raise ValueError("standard pallet length must not exceed the mild oversize length")
        if self.standard_pallet_width_cm > self.mild_oversize_width_cm:
            raise ValueError("standard pallet width must not exceed the mild oversize width")
        if self.mild_oversize_length_cm > self.expansion_trigger_length_cm:
            raise ValueError("mild oversize length must not exceed the expansion trigger length")
        if self.mild_oversize_width_cm > self.expansion_trigger_width_cm:
            raise ValueError("mild oversize width must not exceed the expansion trigger width")
        if self.expansion_grace_cm > min(
            self.standard_pallet_length_cm, self.standard_pallet_width_cm
        ):
            raise ValueError("expansion grace must not exceed either pallet dimension")
        if self.weight_basis_kg > self.unit_auto_weight_max_kg:
            raise ValueError("weight basis must not exceed the automatic unit weight limit")
        if self.normal_board_height_cm > self.high_board_height_cm:
            raise ValueError("normal board height must not exceed the high board height")

        codes = [profile.code for profile in self.vehicle_profiles]
        if len(codes) != len(set(codes)):
            raise ValueError("vehicle profile codes must be unique")
        missing = self.REQUIRED_VEHICLE_CODES.difference(codes)
        if missing:
            missing_text = ", ".join(sorted(missing))
            raise ValueError(f"missing required vehicle profile codes: {missing_text}")
        return self

    # Readable aliases used by calculation and audit code.  They intentionally
    # remain properties so the published JSON has one stable canonical shape.
    @property
    def standard_pallet_long_cm(self) -> Decimal:
        return self.standard_pallet_length_cm

    @property
    def standard_pallet_short_cm(self) -> Decimal:
        return self.standard_pallet_width_cm

    @property
    def long_expansion_trigger_cm(self) -> Decimal:
        return self.expansion_trigger_length_cm

    @property
    def short_expansion_trigger_cm(self) -> Decimal:
        return self.expansion_trigger_width_cm

    @property
    def repeated_boundary_grace_cm(self) -> Decimal:
        return self.expansion_grace_cm

    @property
    def weight_per_pallet_kg(self) -> Decimal:
        return self.weight_basis_kg

    @property
    def normal_height_limit_cm(self) -> Decimal:
        return self.normal_board_height_cm

    @property
    def auto_height_limit_cm(self) -> Decimal:
        return self.high_board_height_cm

    @property
    def max_unit_weight_kg(self) -> Decimal:
        return self.unit_auto_weight_max_kg

    @property
    def deterministic_packing_node_limit(self) -> int:
        return self.packing_node_limit

    @property
    def mild_oversize_long_cm(self) -> Decimal:
        return self.mild_oversize_length_cm

    @property
    def mild_oversize_short_cm(self) -> Decimal:
        return self.mild_oversize_width_cm

    @property
    def max_single_unit_weight_kg(self) -> Decimal:
        return self.unit_auto_weight_max_kg

    @property
    def footprint_fee_usd(self) -> Decimal:
        return self.footprint_surcharge

    @property
    def medium_oversize_fee_usd(self) -> Decimal:
        return self.medium_oversize_surcharge

    @property
    def high_board_fee_usd(self) -> Decimal:
        return self.high_board_surcharge

    @property
    def heavy_fee_usd(self) -> Decimal:
        return self.heavy_surcharge


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
    "OversizePalletRuleConfig",
    "VehicleProfile",
    "default_oversize_pallet_rule",
]
