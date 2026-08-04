from decimal import Decimal

from packages.quote_engine.fcl import FCLCargoItem, FCLQuoteDraft, calculate_cargo


def test_line_total_weight_and_volume_are_included_in_authoritative_totals():
    cargo = calculate_cargo(
        FCLQuoteDraft(
            cargo_items=[
                FCLCargoItem(
                    quantity=2,
                    length=100,
                    width=100,
                    height=100,
                    line_total_weight=Decimal("20"),
                    total_volume_cbm=Decimal("2"),
                )
            ]
        )
    )

    assert cargo.total_weight_kg == Decimal("20.00")
    assert cargo.total_volume_cbm == Decimal("2.000")
    assert "max_single_weight_unknown" in cargo.conflicts


def test_partial_rows_cannot_use_declared_totals_as_automatic_substitute():
    cargo = calculate_cargo(
        FCLQuoteDraft(
            declared_total_weight_kg=Decimal("100"),
            declared_total_volume_cbm=Decimal("10"),
            cargo_items=[FCLCargoItem(quantity=1, weight_kg=Decimal("40"))],
        )
    )

    assert "cargo_items_incomplete" in cargo.conflicts
    assert cargo.total_weight_kg is None
    assert cargo.total_volume_cbm is None
