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
    ("length", "width", "pallets", "surcharge"),
    [
        ("121.92", "101.60", 1, Decimal("0")),
        ("122", "102", 1, Decimal("25")),
        ("149", "121", 1, Decimal("50")),
        ("150", "100", 2, Decimal("0")),
        ("243", "100", 2, Decimal("0")),
        ("245", "100", 2, Decimal("25")),
        ("248.84", "100", 2, Decimal("25")),
        ("248.84", "101.6", 2, Decimal("25")),
        ("249", "100", 3, Decimal("0")),
        ("200", "130", 3, Decimal("0")),
        ("273", "100", 3, Decimal("0")),
        ("230", "150", 3, Decimal("0")),
        ("200", "200", 4, Decimal("0")),
    ],
)
def test_billing_dimensions_follow_published_rule(
    length: str, width: str, pallets: int, surcharge: Decimal
) -> None:
    result = calculate_billing_pallets([unit(length, width)], RULE)

    assert result.billing_pallets == pallets
    assert result.components["total_size_pallets"] == pallets
    assert result.surcharges.get("total_surcharge", Decimal("0")) == surcharge
    assert not result.manual_review_required


def test_boundary_grace_is_one_footprint_fee_when_both_axes_hit() -> None:
    result = calculate_billing_pallets([unit("248.84", "101.6")], RULE)

    assert result.surcharges["footprint_surcharge"] == Decimal("25")
    assert result.surcharges["total_surcharge"] == Decimal("25")


def test_quantity_is_physical_handling_units_not_customer_piece_count() -> None:
    result = calculate_billing_pallets(
        [unit("150", "100", quantity=7, contained=36)],
        RULE,
        declared_customer_piece_count=36,
    )

    assert result.billing_pallets == 14
    assert result.components["total_size_pallets"] == 14


def test_changing_customer_piece_total_does_not_change_size_pallets() -> None:
    rows = [unit("150", "100", quantity=7, contained=36)]

    first = calculate_billing_pallets(rows, RULE, declared_customer_piece_count=36)
    second = calculate_billing_pallets(rows, RULE, declared_customer_piece_count=100)

    assert first.components["total_size_pallets"] == second.components["total_size_pallets"] == 14
    assert second.manual_review_required
    assert "customer_piece_count_mismatch" in second.risk_tags


def test_partial_customer_piece_rows_are_skipped_not_assumed() -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6", quantity=2, contained=None)],
        RULE,
        declared_customer_piece_count=100,
    )

    assert result.billing_pallets == 2
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


@pytest.mark.parametrize("invalid_rule", [{"weight_basis_kg": Decimal("-1")}, object()])
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
    assert result.billing_pallets == 3


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
def test_one_thousand_kg_unit_is_auto_and_heavy_surcharged(weight: str) -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", weight=weight)], RULE)

    assert not result.manual_review_required
    assert result.surcharges["heavy_surcharge"] == Decimal("75")


def test_unit_over_one_thousand_kg_is_manual() -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", weight="1000.01")], RULE)

    assert result.manual_review_required
    assert "handling_unit_weight_over_auto_limit" in result.risk_tags


def test_height_surcharge_does_not_add_size_pallets() -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", height="190")], RULE)

    assert result.billing_pallets == 1
    assert result.surcharges["high_board_surcharge"] == Decimal("50")
    assert not result.manual_review_required


def test_height_over_auto_limit_is_manual() -> None:
    result = calculate_billing_pallets([unit("121.92", "101.6", height="210.01")], RULE)

    assert result.manual_review_required
    assert "handling_unit_height_over_auto_limit" in result.risk_tags


def test_declared_pallet_count_is_a_lower_bound() -> None:
    result = calculate_billing_pallets(
        [unit("121.92", "101.6")], RULE, explicit_pallet_count=8
    )

    assert result.billing_pallets == 8
    assert result.components["total_size_pallets"] == 1


def test_stackability_does_not_reduce_billing_pallets() -> None:
    non_stackable = calculate_billing_pallets(
        [unit("121.92", "101.6", quantity=2, stackability="non_stackable")], RULE
    )
    stackable = calculate_billing_pallets(
        [
            unit(
                "121.92",
                "101.6",
                quantity=2,
                stackability="stackable",
                max_stack_layers=2,
                max_top_load_kg="500",
            )
        ],
        RULE,
    )

    assert non_stackable.billing_pallets == stackable.billing_pallets == 2


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

    assert result.billing_pallets == 1
    assert not result.manual_review_required
    assert "handling_unit_stack_constraints_missing" in result.risk_tags
    assert result.internal_trace["lines"][0]["normalized_input"]["stackability"] == "unknown"


def test_cbm_does_not_directly_determine_billing_pallets() -> None:
    rows = [unit("121.92", "101.6", height="100")]
    small = calculate_billing_pallets(rows, RULE, declared_total_volume_cbm=Decimal("0.1"))
    large = calculate_billing_pallets(rows, RULE, declared_total_volume_cbm=Decimal("100"))

    assert small.components["total_size_pallets"] == large.components["total_size_pallets"] == 1
    assert "declared_volume_out_of_tolerance" in large.risk_tags


def test_missing_handling_units_never_falls_back_to_legacy_formula() -> None:
    result = calculate_billing_pallets(
        handling_units=None,
        rule=RULE,
        cbm=Decimal("20"),
        weight_kg=Decimal("100"),
        piece_count=36,
        packaging_type="crate",
        longest_side_cm=Decimal("300"),
    )

    assert result.manual_review_required
    assert result.billing_pallets is None
    assert "handling_units_missing" in result.risk_tags
    assert result.components.get("volume_pallets", 0) == 0
    assert result.components.get("long_piece_pallets", 0) == 0


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
    assert line["effective_long_cm"] == Decimal("200")
    assert line["area_ratio"] == Decimal("26000") / Decimal("12387.072")
    assert line["footprint_band"] == "expansion"
    assert result.internal_trace["totals"]["derived_total_volume_cbm"] == Decimal("2.6")
