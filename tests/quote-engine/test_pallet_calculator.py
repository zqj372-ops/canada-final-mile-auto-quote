from decimal import Decimal

import pytest

from packages.quote_engine.oversize_config import default_oversize_pallet_rule
from packages.quote_engine.oversize_models import HandlingUnitInput
from packages.quote_engine.pallet_calculator import calculate_billing_pallets


RULE = default_oversize_pallet_rule()


def unit(
    length: str,
    width: str,
    *,
    height: str = "100",
    weight: str = "100",
    quantity: int = 1,
    packaging: str = "crate",
    contained: int | None = None,
    stackability: str = "unknown",
    max_stack_layers: int | None = None,
    max_top_load_kg: str | None = None,
) -> HandlingUnitInput:
    values: dict[str, object] = {
        "quantity": quantity,
        "packaging_type": packaging,
        "length_cm": Decimal(length),
        "width_cm": Decimal(width),
        "height_cm": Decimal(height),
        "unit_weight_kg": Decimal(weight),
        "contained_customer_pieces": contained,
        "stackability": stackability,
    }
    if max_stack_layers is not None:
        values["max_stack_layers"] = max_stack_layers
    if max_top_load_kg is not None:
        values["max_top_load_kg"] = Decimal(max_top_load_kg)
    return HandlingUnitInput(**values)


@pytest.mark.parametrize(
    ("length", "width", "height", "pallets", "position_slots"),
    [
        # Sub-pallet units consolidate into the volume branch: 0 positions.
        ("100", "100", "100", 1, 0),
        # GMA pallet (121.92cm) exceeds the 120cm long-piece line -> 2 pallets.
        ("121.92", "101.60", "100", 2, 0),
        # Design v2 2.3 examples: oversized footprints bill by position.
        ("122", "102", "100", 2, 2),
        ("200", "130", "100", 3, 3),
        ("200", "200", "50", 4, 4),
        ("249", "100", "100", 3, 3),
        ("273", "100", "100", 3, 3),
        ("230", "150", "100", 3, 3),
    ],
)
def test_billing_dimensions_follow_published_rule(
    length: str, width: str, height: str, pallets: int, position_slots: int
) -> None:
    result = calculate_billing_pallets([unit(length, width, height=height)], RULE)

    assert result.billing_pallets == pallets
    assert result.components["position_pallets"] == position_slots
    assert result.components["total_size_pallets"] == position_slots
    assert result.surcharges.get("total_surcharge", Decimal("0")) == Decimal("0")
    assert not result.manual_review_required


def test_volume_pallets_use_whole_order_volume_equivalent() -> None:
    # 5 x 1 CBM cartons bill ceil(5/2)=3, not 5 per-unit positions.
    result = calculate_billing_pallets(
        [unit("100", "100", quantity=5, contained=5)],
        RULE,
        declared_customer_piece_count=5,
        declared_total_volume_cbm=Decimal("5"),
    )

    assert result.components["volume_pallets"] == 3
    assert result.billing_pallets == 3
    assert not result.manual_review_required


def test_quantity_is_physical_handling_units_not_customer_piece_count() -> None:
    result = calculate_billing_pallets(
        [unit("150", "100", quantity=7, contained=36)],
        RULE,
        declared_customer_piece_count=36,
    )

    assert result.billing_pallets == 14
    assert result.components["position_pallets"] == 14


def test_changing_customer_piece_total_does_not_change_size_pallets() -> None:
    rows = [unit("150", "100", quantity=7, contained=36)]

    first = calculate_billing_pallets(rows, RULE, declared_customer_piece_count=36)
    second = calculate_billing_pallets(rows, RULE, declared_customer_piece_count=100)

    assert first.components["position_pallets"] == second.components["position_pallets"] == 14
    assert second.manual_review_required
    assert "customer_piece_count_mismatch" in second.risk_tags


def test_partial_customer_piece_rows_are_skipped_not_assumed() -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6", quantity=2, contained=None)],
        RULE,
        declared_customer_piece_count=100,
    )

    assert result.billing_pallets == 4
    assert "customer_piece_count_check_skipped" in result.risk_tags
    assert not result.manual_review_required


def test_weight_uses_derived_units_and_tolerated_declared_weight() -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6", quantity=2, weight="500")],
        RULE,
        declared_total_weight_kg=Decimal("1040"),
    )

    assert result.components["derived_total_weight_kg"] == Decimal("1000")
    assert result.components["calculation_weight_kg"] == Decimal("1040")
    assert result.components["weight_pallets"] == 3
    assert not result.manual_review_required


def test_weight_tolerance_boundary_rejects_declaration_beyond_max_basis() -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6", quantity=2, weight="500")],
        RULE,
        declared_total_weight_kg=Decimal("1055"),
    )

    assert result.manual_review_required
    assert "declared_weight_out_of_tolerance" in result.risk_tags


@pytest.mark.parametrize("invalid_rule", [{"volume_cbm_per_pallet": Decimal("-1")}, object()])
def test_invalid_rule_fails_closed_with_stable_trace(invalid_rule: object) -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6")], invalid_rule  # type: ignore[arg-type]
    )

    assert result.manual_review_required
    assert result.billing_pallets is None
    assert "oversize_rule_invalid" in result.risk_tags
    assert result.internal_trace["rule_validation"]["status"] == "invalid"
    assert result.internal_trace["rule_validation"]["risk_code"] == "oversize_rule_invalid"


def test_out_of_tolerance_weight_is_manual() -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6", quantity=2, weight="500")],
        RULE,
        declared_total_weight_kg=Decimal("1200"),
    )

    assert result.manual_review_required
    assert "declared_weight_out_of_tolerance" in result.risk_tags
    # long-pieces 4 > weight 3 > volume 2; candidate kept for audit only.
    assert result.billing_pallets == 4


@pytest.mark.parametrize("non_finite", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")])
@pytest.mark.parametrize("field", ["length_cm", "unit_weight_kg"])
def test_non_finite_handling_unit_values_are_manual(non_finite: Decimal, field: str) -> None:
    payload: dict[str, object] = {
        "quantity": 1,
        "packaging_type": "crate",
        "length_cm": Decimal("121.92"),
        "width_cm": Decimal("101.6"),
        "height_cm": Decimal("100"),
        "unit_weight_kg": Decimal("100"),
    }
    payload[field] = non_finite

    result = calculate_billing_pallets([payload], RULE)

    assert result.manual_review_required
    expected_risk = (
        "handling_unit_dimensions_missing"
        if field == "length_cm"
        else "handling_unit_weight_missing"
    )
    assert expected_risk in result.risk_tags


@pytest.mark.parametrize("weight", ["1000", "1000.00"])
def test_one_thousand_kg_unit_is_auto_without_surcharge(weight: str) -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", weight=weight)], RULE)

    assert not result.manual_review_required
    # v2 has no heavy surcharge: heavy freight enters the table price through
    # weight pallets (design v2 4.4).
    assert result.surcharges["heavy_surcharge"] == Decimal("0")
    assert result.components["weight_pallets"] == 2


def test_unit_over_one_thousand_kg_is_manual() -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", weight="1000.01")], RULE)

    assert result.manual_review_required
    assert "unit_weight_over_mechanical_limit" in result.risk_tags


def test_height_does_not_surcharge_or_block() -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", height="210.01")], RULE)

    # Height no longer carries a fee or hard gate; volume covers the size.
    assert result.surcharges["high_board_surcharge"] == Decimal("0")
    assert not result.manual_review_required


def test_floor_slots_above_four_positions_are_manual() -> None:
    result = calculate_billing_pallets([unit("300", "200")], RULE)

    assert result.manual_review_required
    assert "oversize_floor_slots_exceeded" in result.risk_tags


def test_long_pieces_bill_two_pallets_each_not_total_box_count() -> None:
    # Regression lock: "36 箱,其中 7 件长件" -> 14, never 36x2.
    result = calculate_billing_pallets(
        [unit("130", "50", quantity=7, contained=7)],
        RULE,
        declared_customer_piece_count=36,
    )

    assert result.components["long_piece_pallets"] == 14
    assert result.billing_pallets == 14
    assert "customer_piece_count_mismatch" in result.risk_tags


def test_short_pieces_do_not_trigger_long_piece_branch() -> None:
    result = calculate_billing_pallets([unit("119", "100", quantity=3)], RULE)

    assert result.components["long_piece_pallets"] == 0


def test_wooden_crates_bill_one_pallet_each_never_carton_fallback() -> None:
    # SOP v1.11 lock: 7 件木箱 = 7 托.
    result = calculate_billing_pallets(
        [unit("100", "80", quantity=7, packaging="wooden_crate", contained=7)],
        RULE,
        declared_customer_piece_count=7,
    )

    assert result.components["wooden_crate_pallets"] == 7
    assert result.billing_pallets == 7


def test_long_wooden_crate_bills_two_pallets_each() -> None:
    result = calculate_billing_pallets(
        [unit("130", "80", quantity=3, packaging="wooden_crate")], RULE
    )

    assert result.components["wooden_crate_pallets"] == 6
    assert result.billing_pallets == 6


def test_explicit_pallet_count_adopted_only_within_tolerance() -> None:
    result = calculate_billing_pallets(
        [unit("200", "130", quantity=2, weight="1000")],
        RULE,
        explicit_pallet_count=7,
    )

    # Derived = max(positions 6, volume 2, weight 4) = 6; |7-6|/6 <= 0.5.
    assert result.components["explicit_pallet_count"] == 7
    assert result.billing_pallets == 7
    assert not result.manual_review_required


def test_explicit_pallet_count_conflict_is_manual() -> None:
    result = calculate_billing_pallets(
        [unit("200", "130", quantity=2, weight="1000")],
        RULE,
        explicit_pallet_count=30,
    )

    assert result.manual_review_required
    assert "explicit_pallet_count_conflict" in result.risk_tags


def test_billing_above_twenty_six_pallets_is_manual() -> None:
    result = calculate_billing_pallets(
        [unit("150", "100", quantity=27, weight="1000")], RULE
    )

    # position 54, weight ceil(27000/500)=54 -> 54; >26 => manual.
    assert result.billing_pallets == 54
    assert result.manual_review_required
    assert "billing_pallets_out_of_table" in result.risk_tags


def test_stackability_does_not_reduce_billing_pallets() -> None:
    non_stackable = calculate_billing_pallets(
        [unit("150", "100", quantity=2, stackability="non_stackable")], RULE
    )
    stackable = calculate_billing_pallets(
        [
            unit(
                "150",
                "100",
                quantity=2,
                stackability="stackable",
                max_stack_layers=2,
                max_top_load_kg="500",
            )
        ],
        RULE,
    )

    assert non_stackable.billing_pallets == stackable.billing_pallets == 4


def test_incomplete_stack_constraints_downgrade_to_unknown_without_blocking() -> None:
    result = calculate_billing_pallets(
        [
            {
                "quantity": 1,
                "packaging_type": "pallet",
                "length_cm": "121.92",
                "width_cm": "101.6",
                "height_cm": "100",
                "unit_weight_kg": "100",
                "stackability": "stackable",
            }
        ],
        RULE,
    )

    # GMA-length pallet is a long piece (>120cm) -> 2 pallets; still automatic.
    assert result.billing_pallets == 2
    assert not result.manual_review_required
    assert "handling_unit_stack_constraints_missing" in result.risk_tags
    assert result.internal_trace["lines"][0]["normalized_input"]["stackability"] == "unknown"


def test_declared_volume_within_tolerance_lifts_calculation_volume() -> None:
    rows = [unit("100", "100", height="100", quantity=2, weight="100")]
    small = calculate_billing_pallets(rows, RULE, declared_total_volume_cbm=Decimal("0.1"))
    lifted = calculate_billing_pallets(rows, RULE, declared_total_volume_cbm=Decimal("2.4"))

    assert small.components["calculation_total_volume_cbm"] == Decimal("2")
    assert small.components["volume_pallets"] == 1
    assert lifted.components["calculation_total_volume_cbm"] == Decimal("2.4")
    assert lifted.components["volume_pallets"] == 2
    assert "declared_volume_out_of_tolerance" not in lifted.risk_tags


def test_aggregate_fallback_uses_whole_order_formula() -> None:
    result = calculate_billing_pallets(
        handling_units=None,
        rule=RULE,
        cbm=Decimal("20"),
        weight_kg=Decimal("1000"),
        piece_count=36,
        packaging_type="crate",
        longest_side_cm=Decimal("300"),
    )

    assert result.components["volume_pallets"] == 10
    assert result.components["weight_pallets"] == 2
    assert result.billing_pallets == 10
    assert not result.manual_review_required
    assert "aggregate_based_quote" in result.risk_tags
    assert "long_piece_count_unconfirmed" in result.risk_tags


def test_aggregate_fallback_can_be_disabled() -> None:
    rule = RULE.model_copy(update={"aggregate_quote_enabled": False})
    result = calculate_billing_pallets(
        handling_units=None,
        rule=rule,
        cbm=Decimal("20"),
        weight_kg=Decimal("1000"),
        piece_count=36,
        packaging_type="crate",
    )

    assert result.manual_review_required
    assert result.billing_pallets is None
    assert "handling_units_missing" in result.risk_tags


def test_aggregate_without_volume_or_weight_is_manual() -> None:
    result = calculate_billing_pallets(
        handling_units=[],
        rule=RULE,
        cbm=Decimal("0"),
        weight_kg=Decimal("0"),
        piece_count=36,
        packaging_type="crate",
    )

    assert result.manual_review_required
    assert "aggregate_info_insufficient" in result.risk_tags


def test_aggregate_incomplete_rows_feed_the_fallback_not_manual() -> None:
    result = calculate_billing_pallets(
        [
            {
                "quantity": 20,
                "packaging_type": "carton",
                "length_cm": None,
                "width_cm": None,
                "height_cm": None,
                "unit_weight_kg": None,
                "contained_customer_pieces": 20,
            }
        ],
        RULE,
        declared_customer_piece_count=20,
        declared_total_volume_cbm=Decimal("2"),
        declared_total_weight_kg=Decimal("300"),
    )

    assert result.billing_pallets == 1
    assert not result.manual_review_required
    assert "aggregate_based_quote" in result.risk_tags
    assert result.internal_trace["lines"][0]["status"] == "invalid"


def test_flexible_package_deal_flat_rate() -> None:
    result = calculate_billing_pallets(
        [
            unit(
                "100",
                "50",
                height="40",
                weight="25",
                quantity=76,
                packaging="woven_bag",
                contained=76,
                stackability="stackable",
                max_stack_layers=4,
                max_top_load_kg="100",
            )
        ],
        RULE,
        declared_customer_piece_count=76,
        is_stackable=True,
    )

    assert result.pricing_mode == "flat_rate"
    assert result.flat_rate_usd == Decimal("580")
    assert not result.manual_review_required


def test_flexible_package_deal_below_min_pieces_stays_per_pallet() -> None:
    result = calculate_billing_pallets(
        [unit("100", "50", height="40", weight="25", quantity=49, packaging="woven_bag", contained=49)],
        RULE,
        declared_customer_piece_count=49,
    )

    assert result.pricing_mode == "per_pallet"
    assert not result.manual_review_required


def test_flexible_package_deal_missing_evidence_is_manual() -> None:
    result = calculate_billing_pallets(
        [unit("100", "50", height="40", weight="25", quantity=76, packaging="woven_bag")],
        RULE,
        declared_customer_piece_count=76,
    )

    assert result.manual_review_required
    assert "flexible_package_deal_info_missing" in result.risk_tags


def test_low_density_adds_soft_risk_only() -> None:
    result = calculate_billing_pallets(
        [unit("100", "100", height="100", weight="10")], RULE
    )

    assert "low_density_dimensional_risk" in result.risk_tags
    assert not result.manual_review_required


def test_vehicle_capacity_is_reference_only_and_never_blocks() -> None:
    # A 16.5m-long piece exceeds every vehicle floor but stays under the
    # mechanical weight limit: dimension risk is emitted, the quote continues.
    result = calculate_billing_pallets(
        [unit("1650", "30", height="200", weight="900")], RULE
    )

    assert result.internal_trace["vehicle_capacity"]
    assert "oversize_vehicle_dimension_exceeded" in result.risk_tags
    assert not result.manual_review_required


def test_invalid_handling_unit_returns_manual_risk_tags() -> None:
    result = calculate_billing_pallets(
        [
            {
                "quantity": 1,
                "packaging_type": "crate",
                "length_cm": None,
                "width_cm": 100,
                "height_cm": 100,
                "unit_weight_kg": None,
            }
        ],
        RULE,
    )

    assert result.manual_review_required
    assert "handling_unit_dimensions_missing" in result.risk_tags
    assert "handling_unit_weight_missing" in result.risk_tags


def test_internal_trace_keeps_replayable_source_fields_on_valid_line() -> None:
    payload = {
        "quantity": 1,
        "packaging_type": "crate",
        "length_cm": Decimal("121.92"),
        "width_cm": Decimal("101.6"),
        "height_cm": Decimal("100"),
        "unit_weight_kg": Decimal("100"),
        "cbm": Decimal("1.2"),
        "contained_customer_pieces": 4,
        "source_span": "quote:4-5",
    }

    result = calculate_billing_pallets([payload], RULE)
    line = result.internal_trace["lines"][0]

    assert line["contained_customer_pieces"] == 4
    assert line["supplied_unit_cbm"] == Decimal("1.2")
    assert line["source_span"] == "quote:4-5"
    assert line["raw_input"]["cbm"] == Decimal("1.2")
    assert line["normalized_input"]["cbm"] == Decimal("1.2")


def test_invalid_rows_skip_customer_piece_check_and_keep_safe_trace() -> None:
    result = calculate_billing_pallets(
        [
            unit("121.92", "101.6", contained=4),
            {
                "quantity": 1,
                "packaging_type": "crate",
                "length_cm": None,
                "private_customer_note": "do not retain",
            },
        ],
        RULE,
        declared_customer_piece_count=4,
    )

    invalid_line = result.internal_trace["lines"][1]
    assert result.manual_review_required
    assert result.internal_trace["totals"]["customer_piece_check"] == "skipped_invalid_rows"
    assert invalid_line["status"] == "invalid"
    assert invalid_line["raw_field_summary"]["length_cm"] is None
    assert "private_customer_note" not in invalid_line["raw_field_summary"]


@pytest.mark.parametrize("invalid_explicit", [Decimal("1.5"), Decimal("NaN"), -1, "not-a-count"])
def test_invalid_explicit_pallet_count_is_manual(invalid_explicit: object) -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6")], RULE, explicit_pallet_count=invalid_explicit  # type: ignore[arg-type]
    )

    assert result.manual_review_required
    assert "explicit_pallet_count_invalid" in result.risk_tags


def test_internal_trace_keeps_decimal_dimensions_and_rule_identity() -> None:
    result = calculate_billing_pallets([unit("200", "130", weight="900")], RULE)

    assert result.internal_trace["rule_id"] == RULE.rule_id
    line = result.internal_trace["lines"][0]
    assert line["floor_area_cm2"] == Decimal("26000")
    assert line["position_slots"] == 3
    assert line["footprint_band"] == "expansion"
    assert result.internal_trace["totals"]["derived_total_volume_cbm"] == Decimal("2.6")
