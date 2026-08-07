from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.quote_engine.oversize_config import (
    OversizePalletRuleConfig,
    VehicleProfile,
    default_oversize_pallet_rule,
)
from packages.quote_engine.oversize_models import HandlingUnitInput


def test_default_rule_matches_na_oversize_temp_v1_contract() -> None:
    rule = default_oversize_pallet_rule()

    assert rule.rule_id == "NA_OVERSIZE_TEMP_V1"
    assert rule.standard_pallet_length_cm == Decimal("121.92")
    assert rule.standard_pallet_width_cm == Decimal("101.60")
    assert rule.standard_pallet_area_cm2 == Decimal("12387.072")
    assert rule.mild_oversize_length_cm == Decimal("135")
    assert rule.mild_oversize_width_cm == Decimal("110")
    assert rule.expansion_trigger_length_cm == Decimal("150")
    assert rule.expansion_trigger_width_cm == Decimal("122")
    assert rule.expansion_grace_cm == Decimal("5")
    assert rule.area_tolerance_ratio == Decimal("0.02")
    assert rule.weight_basis_kg == Decimal("500")
    assert rule.normal_board_height_cm == Decimal("180")
    assert rule.high_board_height_cm == Decimal("210")
    assert rule.unit_auto_weight_max_kg == Decimal("1000")
    assert rule.footprint_surcharge == Decimal("25")
    assert rule.medium_oversize_surcharge == Decimal("50")
    assert rule.high_board_surcharge == Decimal("50")
    assert rule.heavy_surcharge == Decimal("75")
    assert rule.customer_piece_tolerance_absolute == 2
    assert rule.customer_piece_tolerance_ratio == Decimal("0.05")
    assert rule.weight_tolerance_absolute_kg == Decimal("50")
    assert rule.weight_tolerance_ratio == Decimal("0.05")
    assert rule.volume_tolerance_absolute_cbm == Decimal("0.5")
    assert rule.volume_tolerance_ratio == Decimal("0.10")
    assert rule.max_auto_vehicles == 3
    assert rule.packing_node_limit > 0

    profiles = {profile.code: profile for profile in rule.vehicle_profiles}
    assert set(profiles) == {"26_non_cdl", "26_cdl", "53_dry_van"}
    assert profiles["26_non_cdl"].model_dump() == {
        "code": "26_non_cdl",
        "label": "26尺非CDL",
        "length_cm": Decimal("762"),
        "width_cm": Decimal("243.84"),
        "height_cm": Decimal("243.84"),
        "volume_cbm": Decimal("45.3"),
        "payload_kg": Decimal("4536"),
        "common_pallet_limit": 12,
        "tight_pallet_limit": 14,
        "comparable_base_price": None,
    }
    assert profiles["26_cdl"].payload_kg == Decimal("7711")
    assert profiles["53_dry_van"].model_dump(exclude={"label", "comparable_base_price"}) == {
        "code": "53_dry_van",
        "length_cm": Decimal("1600.2"),
        "width_cm": Decimal("250.19"),
        "height_cm": Decimal("279.4"),
        "volume_cbm": Decimal("110.4"),
        "payload_kg": Decimal("19958"),
        "common_pallet_limit": 26,
        "tight_pallet_limit": 30,
    }


def test_default_rule_is_a_fresh_copy() -> None:
    first = default_oversize_pallet_rule()
    second = default_oversize_pallet_rule()

    assert first is not second
    assert first.vehicle_profiles is not second.vehicle_profiles
    first.vehicle_profiles[0].label = "changed"
    assert second.vehicle_profiles[0].label == "26尺非CDL"


@pytest.mark.parametrize(
    "payload",
    [
        {"quantity": 0},
        {"quantity": 1, "length_cm": 1, "width_cm": 1, "height_cm": 1, "unit_weight_kg": 1},
        {
            "quantity": 1,
            "packaging_type": "crate",
            "length_cm": -1,
            "width_cm": 1,
            "height_cm": 1,
            "unit_weight_kg": 1,
        },
        {
            "quantity": 1,
            "packaging_type": "crate",
            "length_cm": 1,
            "width_cm": 1,
            "height_cm": 1,
            "unit_weight_kg": 1,
            "stackability": "stackable",
        },
        {
            "quantity": 1,
            "packaging_type": "crate",
            "length_cm": 1,
            "width_cm": 1,
            "height_cm": 1,
            "unit_weight_kg": 1,
            "max_stack_layers": 1,
        },
    ],
)
def test_handling_unit_rejects_invalid_payload(payload: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        HandlingUnitInput(**payload)


def test_handling_unit_accepts_unknown_and_non_stackable_without_stack_limits() -> None:
    for stackability in ("unknown", "non_stackable"):
        unit = HandlingUnitInput(
            quantity=2,
            packaging_type="crate",
            length_cm=Decimal("200"),
            width_cm=Decimal("130"),
            height_cm=Decimal("100"),
            unit_weight_kg=Decimal("900"),
            stackability=stackability,
            contained_customer_pieces=12,
        )
        assert unit.quantity == 2
        assert unit.stackability == stackability


def test_handling_unit_accepts_unit_gross_weight_design_alias() -> None:
    unit = HandlingUnitInput(
        quantity=1,
        packaging_type="crate",
        length_cm=Decimal("121.92"),
        width_cm=Decimal("101.60"),
        height_cm=Decimal("100"),
        unit_gross_weight=Decimal("240"),
    )

    assert unit.unit_weight_kg == Decimal("240")
    assert unit.unit_gross_weight_kg == Decimal("240")


def test_handling_unit_extra_fields_are_forbidden_and_customer_pieces_do_not_change_quantity() -> None:
    with pytest.raises(ValidationError):
        HandlingUnitInput(
            quantity=1,
            packaging_type="crate",
            length_cm=1,
            width_cm=1,
            height_cm=1,
            unit_weight_kg=1,
            unexpected="not allowed",
        )

    unit = HandlingUnitInput(
        quantity=2,
        packaging_type="carton",
        length_cm=1,
        width_cm=1,
        height_cm=1,
        unit_weight_kg=1,
        contained_customer_pieces=99,
    )
    assert unit.quantity == 2
    assert unit.contained_customer_pieces == 99


def test_rule_rejects_invalid_ordering_and_vehicle_limits() -> None:
    defaults = default_oversize_pallet_rule().model_dump()

    with pytest.raises(ValidationError):
        OversizePalletRuleConfig(**{**defaults, "rule_id": "   "})

    with pytest.raises(ValidationError):
        OversizePalletRuleConfig(
            **{**defaults, "expansion_trigger_length_cm": Decimal("100")}
        )
    with pytest.raises(ValidationError):
        OversizePalletRuleConfig(
            **{
                **defaults,
                "vehicle_profiles": [
                    {
                        **defaults["vehicle_profiles"][0],
                        "common_pallet_limit": 15,
                        "tight_pallet_limit": 14,
                    },
                    *defaults["vehicle_profiles"][1:],
                ],
            }
        )
    with pytest.raises(ValidationError):
        OversizePalletRuleConfig(**{**defaults, "max_auto_vehicles": 4})
    with pytest.raises(ValidationError):
        OversizePalletRuleConfig(
            **{
                **defaults,
                "vehicle_profiles": [
                    defaults["vehicle_profiles"][0],
                    defaults["vehicle_profiles"][1],
                ],
            }
        )


def test_vehicle_profile_validates_ordering_and_positive_fields() -> None:
    with pytest.raises(ValidationError):
        VehicleProfile(
            code="x",
            label="x",
            length_cm=1,
            width_cm=1,
            height_cm=1,
            volume_cbm=1,
            payload_kg=1,
            common_pallet_limit=2,
            tight_pallet_limit=1,
        )
