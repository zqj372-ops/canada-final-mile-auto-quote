from decimal import Decimal

import pytest

from packages.quote_engine.oversize_config import VehicleProfile, default_oversize_pallet_rule
from packages.quote_engine.oversize_models import HandlingUnitInput
from packages.quote_engine.vehicle_packing import (
    PackingStatus,
    pack_vehicle,
    select_vehicle,
)


RULE = default_oversize_pallet_rule()


def unit(
    length: str,
    width: str,
    *,
    height: str = "100",
    weight: str = "100",
    quantity: int = 1,
    stackability: str = "unknown",
    max_stack_layers: int | None = None,
    max_top_load_kg: str | None = None,
    floor_rotation_allowed: bool = True,
) -> HandlingUnitInput:
    values: dict[str, object] = {
        "quantity": quantity,
        "packaging_type": "crate",
        "length_cm": Decimal(length),
        "width_cm": Decimal(width),
        "height_cm": Decimal(height),
        "unit_weight_kg": Decimal(weight),
        "stackability": stackability,
        "floor_rotation_allowed": floor_rotation_allowed,
    }
    if max_stack_layers is not None:
        values["max_stack_layers"] = max_stack_layers
    if max_top_load_kg is not None:
        values["max_top_load_kg"] = Decimal(max_top_load_kg)
    return HandlingUnitInput(**values)


def profile(code: str):
    return next(item for item in RULE.vehicle_profiles if item.code == code)


def test_standard_units_fit_deterministically_on_26_foot_floor() -> None:
    result = pack_vehicle([unit("121.92", "101.6", quantity=4)], profile("26_non_cdl"), rule=RULE)

    assert result.status is PackingStatus.FIT
    assert result.vehicle_code == "26_non_cdl"
    assert result.vehicle_count == 1
    assert result.floor_columns == 4
    assert result.tight_loading is False
    assert len(result.placements) == 4
    assert result.placements == pack_vehicle(
        [unit("121.92", "101.6", quantity=4)], profile("26_non_cdl"), rule=RULE
    ).placements


def test_large_batch_requires_53_foot_vehicle() -> None:
    result = select_vehicle([unit("121.92", "101.6", quantity=15)], rule=RULE)

    assert result.status is PackingStatus.FIT
    assert result.vehicle_code == "53_dry_van"
    assert result.vehicle_count == 1
    assert result.floor_columns == 15


def test_single_unit_that_exceeds_all_vehicle_dimensions_is_proven_not_fit() -> None:
    result = select_vehicle([unit("1700", "300", height="300")], rule=RULE)

    assert result.status is PackingStatus.PROVEN_NOT_FIT
    assert "unit_dimensions_exceed_vehicle" in result.reason_codes
    assert result.vehicle_count == 0


def test_rotation_flag_preserves_original_orientation_for_vehicle_layout() -> None:
    allowed = pack_vehicle(
        [unit("100", "250", floor_rotation_allowed=True)], profile("26_non_cdl"), rule=RULE
    )
    forbidden = pack_vehicle(
        [unit("100", "250", floor_rotation_allowed=False)], profile("26_non_cdl"), rule=RULE
    )

    assert allowed.status is PackingStatus.FIT
    assert forbidden.status is PackingStatus.PROVEN_NOT_FIT
    # Billing still normalizes the same physical footprint; packing must not.
    assert allowed.placements[0]["orientation"] == "rotated"


def test_weight_and_volume_are_hard_vehicle_constraints() -> None:
    overweight = pack_vehicle(
        [unit("121.92", "101.6", quantity=10, weight="500")],
        profile("26_non_cdl"),
        rule=RULE,
    )
    overvolume = pack_vehicle(
        [unit("300", "200", height="300", quantity=10, weight="100")],
        profile("26_non_cdl"),
        rule=RULE,
    )

    assert overweight.status is PackingStatus.PROVEN_NOT_FIT
    assert "vehicle_payload_exceeded" in overweight.reason_codes
    assert overvolume.status is PackingStatus.PROVEN_NOT_FIT
    assert "vehicle_volume_exceeded" in overvolume.reason_codes


def test_node_limit_is_inconclusive_not_proven_failure() -> None:
    constrained = RULE.model_copy(update={"packing_node_limit": 1})
    result = pack_vehicle(
        [unit("121.92", "101.6", quantity=2)], profile("26_non_cdl"), rule=constrained
    )

    assert result.status is PackingStatus.INCONCLUSIVE
    assert "packing_node_limit" in result.reason_codes


def test_stackable_units_share_one_floor_column_but_keep_physical_count() -> None:
    result = pack_vehicle(
        [
            unit(
                "121.92",
                "101.6",
                quantity=2,
                height="80",
                stackability="stackable",
                max_stack_layers=2,
                max_top_load_kg="200",
            )
        ],
        profile("26_non_cdl"),
        rule=RULE,
    )

    assert result.status is PackingStatus.FIT
    assert result.floor_columns == 1
    assert result.placements[0]["layers"] == 2
    assert result.placements[0]["unit_quantity"] == 2


def test_stack_height_falls_back_to_unstacked_when_vehicle_height_is_too_low() -> None:
    result = pack_vehicle(
        [
            unit(
                "121.92",
                "101.6",
                quantity=2,
                height="130",
                stackability="stackable",
                max_stack_layers=2,
                max_top_load_kg="200",
            )
        ],
        profile("26_non_cdl"),
        rule=RULE,
    )

    assert result.status is PackingStatus.FIT
    assert result.floor_columns == 2
    assert all(item["layers"] == 1 for item in result.placements)


def test_stack_height_uses_configured_high_board_limit_not_a_hardcoded_210_cm() -> None:
    rule = RULE.model_copy(update={"high_board_height_cm": Decimal("250")})
    result = pack_vehicle(
        [
            unit(
                "121.92",
                "101.6",
                quantity=2,
                height="110",
                stackability="stackable",
                max_stack_layers=2,
                max_top_load_kg="500",
            )
        ],
        profile("26_non_cdl"),
        rule=rule,
    )

    assert result.status is PackingStatus.FIT
    assert result.floor_columns == 1
    assert result.placements[0]["layers"] == 2


def test_invalid_rule_fails_closed_with_stable_reason_code() -> None:
    invalid_rule = {"packing_node_limit": 0}

    result = pack_vehicle([unit("121.92", "101.6")], profile("26_non_cdl"), rule=invalid_rule)
    selected = select_vehicle([unit("121.92", "101.6")], rule=invalid_rule)

    assert result.status is PackingStatus.INCONCLUSIVE
    assert selected.status is PackingStatus.INCONCLUSIVE
    assert "oversize_rule_invalid" in result.reason_codes
    assert "oversize_rule_invalid" in selected.reason_codes


def test_invalid_handling_unit_row_is_not_dropped_for_a_partial_fit() -> None:
    invalid_row = {
        "quantity": 1,
        "packaging_type": "crate",
        "length_cm": None,
        "width_cm": 100,
        "height_cm": 100,
        "unit_weight_kg": 100,
    }

    result = pack_vehicle(
        [unit("121.92", "101.6"), invalid_row], profile("26_non_cdl"), rule=RULE
    )
    selected = select_vehicle([unit("121.92", "101.6"), invalid_row], rule=RULE)

    assert result.status is PackingStatus.PROVEN_NOT_FIT
    assert selected.status is PackingStatus.PROVEN_NOT_FIT
    assert "handling_unit_invalid" in result.reason_codes
    assert "handling_unit_invalid" in selected.reason_codes


def test_multi_vehicle_validation_distributes_adopted_weight_before_capacity_checks() -> None:
    # Thirty-one standard pallets require multiple trucks.  Derived weight is
    # deliberately small, while the adopted order weight only fits three 53s.
    result = select_vehicle(
        [unit("121.92", "101.6", quantity=31)],
        rule=RULE,
        total_weight_kg=Decimal("45000"),
    )

    assert result.status is PackingStatus.FIT
    assert result.vehicle_count == 3
    assert result.payload_kg == Decimal("45000")
    assert len(result.vehicle_code.split("+")) == 3
    assert all(code in {"26_cdl", "53_dry_van"} for code in result.vehicle_code.split("+"))


def test_multi_vehicle_plan_reassembles_same_row_for_stacking() -> None:
    # Each small vehicle fits two floor columns.  Eight units from one
    # homogeneous row fit only when the row is reassembled per vehicle and
    # the declared two-layer stack is preserved.
    small_profiles = [
        profile(code).model_copy(
            update={
                "length_cm": Decimal("200"),
                "width_cm": Decimal("100"),
                "height_cm": Decimal("210"),
                "volume_cbm": Decimal("100"),
                "payload_kg": Decimal("10000"),
                "common_pallet_limit": 2,
                "tight_pallet_limit": 2,
            }
        )
        for code in ("26_non_cdl", "26_cdl", "53_dry_van")
    ]
    rule = RULE.model_copy(update={"vehicle_profiles": small_profiles})

    result = select_vehicle(
        [
            unit(
                "100",
                "100",
                height="100",
                quantity=8,
                stackability="stackable",
                max_stack_layers=2,
                max_top_load_kg="100",
            )
        ],
        rule=rule,
    )

    assert result.status is PackingStatus.FIT
    assert result.vehicle_count == 2
    assert sum(int(placement["unit_quantity"]) for placement in result.placements) == 8
    assert all(placement["layers"] == 2 for placement in result.placements)


def test_multi_vehicle_grid_shortcut_does_not_reject_mixed_rotation_fit() -> None:
    # Four 1x2 dominoes fit a 3x3 floor only with mixed 90-degree rotation,
    # which exceeds the single-orientation grid count of three.  Seven units
    # therefore fit two such vehicles (4+3), and the grid shortcut must not
    # reject that two-vehicle plan for non-standard units.
    small_profiles = [
        profile(code).model_copy(
            update={
                "length_cm": Decimal("3"),
                "width_cm": Decimal("3"),
                "height_cm": Decimal("3"),
                "volume_cbm": Decimal("100"),
                "payload_kg": Decimal("1000"),
                "common_pallet_limit": 1,
                "tight_pallet_limit": 4,
            }
        )
        for code in ("26_non_cdl", "26_cdl", "53_dry_van")
    ]
    rule = RULE.model_copy(update={"vehicle_profiles": small_profiles})

    result = select_vehicle(
        [unit("1", "2", height="1", weight="1", quantity=7)],
        rule=rule,
    )

    assert result.status is PackingStatus.FIT
    assert result.vehicle_count == 2
    assert "vehicle_group_layout_not_fit" not in result.reason_codes


def test_vehicle_tie_break_prefers_price_then_capacity_then_code() -> None:
    rule = RULE.model_copy(
        update={
            "vehicle_profiles": [
                profile("26_non_cdl").model_copy(update={"comparable_base_price": Decimal("100")}),
                profile("26_cdl").model_copy(update={"comparable_base_price": Decimal("90")}),
                profile("53_dry_van").model_copy(update={"comparable_base_price": Decimal("1000")}),
            ]
        }
    )
    result = select_vehicle([unit("121.92", "101.6")], rule=rule)

    assert result.status is PackingStatus.FIT
    assert result.vehicle_code == "26_cdl"


def test_vehicle_tie_break_uses_prices_only_from_fit_candidates() -> None:
    rule = RULE.model_copy(
        update={
            "vehicle_profiles": [
                profile("26_non_cdl").model_copy(update={"comparable_base_price": Decimal("100")}),
                profile("26_cdl").model_copy(update={"comparable_base_price": Decimal("90")}),
                profile("53_dry_van").model_copy(
                    update={
                        "length_cm": Decimal("100"),
                        "width_cm": Decimal("100"),
                        "height_cm": Decimal("100"),
                        "comparable_base_price": None,
                    }
                ),
            ]
        }
    )

    result = select_vehicle([unit("121.92", "101.6")], rule=rule)

    assert result.status is PackingStatus.FIT
    assert result.vehicle_code == "26_cdl"


def test_mixed_rotation_dominoes_are_not_rejected_by_a_homogeneous_grid_shortcut() -> None:
    domino_profile = VehicleProfile(
        code="domino",
        label="3x3 test vehicle",
        length_cm=Decimal("3"),
        width_cm=Decimal("3"),
        height_cm=Decimal("3"),
        volume_cbm=Decimal("1"),
        payload_kg=Decimal("100"),
        common_pallet_limit=1,
        tight_pallet_limit=4,
    )

    result = pack_vehicle(
        [unit("1", "2", quantity=4, height="1", weight="1")], domino_profile, rule=RULE
    )

    assert result.status is PackingStatus.FIT
    assert result.floor_columns == 4


def test_custom_profile_exact_area_rotation_is_not_rejected_by_exact_floor_shortcut() -> None:
    exact_profile = VehicleProfile(
        code="exact_area",
        label="3x3 exact-area test vehicle",
        length_cm=Decimal("3"),
        width_cm=Decimal("3"),
        height_cm=Decimal("3"),
        volume_cbm=Decimal("1"),
        payload_kg=Decimal("100"),
        common_pallet_limit=1,
        tight_pallet_limit=3,
    )

    result = pack_vehicle(
        [unit("1", "3", quantity=3, height="1", weight="1")], exact_profile, rule=RULE
    )

    assert result.status is PackingStatus.FIT
    assert result.floor_columns == 3


def test_dfs_uses_cartesian_x_y_boundaries_for_mixed_custom_rectangles() -> None:
    mixed_profile = VehicleProfile(
        code="mixed_5x3",
        label="5x3 mixed-rectangle test vehicle",
        length_cm=Decimal("5"),
        width_cm=Decimal("3"),
        height_cm=Decimal("3"),
        volume_cbm=Decimal("1"),
        payload_kg=Decimal("100"),
        common_pallet_limit=1,
        tight_pallet_limit=3,
    )

    result = pack_vehicle(
        [
            unit("1", "3", height="1", weight="1"),
            unit("1", "4", height="1", weight="1"),
            unit("2", "3", height="1", weight="1"),
        ],
        mixed_profile,
        rule=RULE,
    )

    assert result.status is PackingStatus.FIT
    assert result.floor_columns == 3


def test_auto_selection_does_not_create_a_fourth_vehicle() -> None:
    result = select_vehicle([unit("121.92", "101.6", quantity=100)], rule=RULE)

    assert result.status in {PackingStatus.PROVEN_NOT_FIT, PackingStatus.INCONCLUSIVE}
    assert result.vehicle_count in {0, 4}
    assert "max_auto_vehicles_exceeded" in result.reason_codes or result.status is PackingStatus.INCONCLUSIVE
