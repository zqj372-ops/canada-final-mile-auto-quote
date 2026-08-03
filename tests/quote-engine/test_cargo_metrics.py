from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.quote_engine.cargo_metrics import CargoMetricItem, calculate_cargo_metrics


def test_calculates_authoritative_totals_from_item_rows():
    result = calculate_cargo_metrics(
        [
            CargoMetricItem(
                quantity=2,
                length=120,
                width=100,
                height=125,
                dimension_unit="cm",
                piece_weights=[785, 800],
                weight_unit="kg",
            )
        ]
    )

    assert result.total_piece_count == 2
    assert result.total_volume_cbm == Decimal("3.000")
    assert result.total_weight_kg == Decimal("1585.00")
    assert result.billing_density_kg_per_cbm == Decimal("528.33")
    assert result.max_single_weight_kg == Decimal("800.00")
    assert result.blocking_conflicts == []


@pytest.mark.parametrize(
    ("dimension_unit", "weight_unit", "expected_volume", "expected_weight"),
    [
        ("mm", "g", Decimal("0.001"), Decimal("1.00")),
        ("m", "kg", Decimal("1.000"), Decimal("1.00")),
        ("in", "lb", Decimal("0.016"), Decimal("1.00")),
    ],
)
def test_converts_supported_units(dimension_unit, weight_unit, expected_volume, expected_weight):
    result = calculate_cargo_metrics(
        [
            CargoMetricItem(
                quantity=1,
                length=1 if dimension_unit == "m" else 100 if dimension_unit == "mm" else 10,
                width=1 if dimension_unit == "m" else 100 if dimension_unit == "mm" else 10,
                height=1 if dimension_unit == "m" else 100 if dimension_unit == "mm" else 10,
                dimension_unit=dimension_unit,
                unit_weight=1000 if weight_unit == "g" else 1 if weight_unit == "kg" else 2.2046226218,
                weight_unit=weight_unit,
            )
        ]
    )

    assert result.total_volume_cbm == expected_volume
    assert result.total_weight_kg == expected_weight


def test_rejects_piece_weight_length_mismatch():
    with pytest.raises(ValidationError, match="piece_weights"):
        CargoMetricItem(
            quantity=2,
            length=1,
            width=1,
            height=1,
            unit_weight=1,
            piece_weights=[1],
        )


def test_marks_conflicting_weight_evidence_and_does_not_choose_a_value():
    result = calculate_cargo_metrics(
        [
            CargoMetricItem(
                quantity=2,
                length=1,
                width=1,
                height=1,
                unit_weight=10,
                piece_weights=[10, 11],
                line_total_weight=20,
            )
        ]
    )

    assert "line_weight_evidence_conflict" in result.blocking_conflicts


def test_line_total_only_cannot_invent_max_single_weight():
    result = calculate_cargo_metrics(
        [
            CargoMetricItem(
                quantity=2,
                length=1,
                width=1,
                height=1,
                line_total_weight=20,
            )
        ]
    )

    assert result.total_weight_kg == Decimal("20.00")
    assert result.max_single_weight_kg is None
    assert "max_single_weight_unknown" in result.blocking_conflicts


def test_declared_totals_are_evidence_only_and_conflicts_block():
    result = calculate_cargo_metrics(
        [
            CargoMetricItem(
                quantity=1,
                length=1,
                width=1,
                height=1,
                unit_weight=10,
            )
        ],
        declared_total_weight_kg=11,
        declared_total_volume_cbm=2,
    )

    assert result.total_weight_kg == Decimal("10.00")
    assert result.declared_total_weight_kg == Decimal("11.00")
    assert "declared_total_weight_conflict" in result.blocking_conflicts
    assert "declared_total_volume_conflict" in result.blocking_conflicts


def test_empty_rows_with_only_declared_totals_block():
    result = calculate_cargo_metrics([], declared_total_weight_kg=100, declared_total_volume_cbm=2)

    assert "cargo_items_incomplete" in result.blocking_conflicts
    assert result.total_weight_kg == Decimal("0.00")
