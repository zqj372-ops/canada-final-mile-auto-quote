from decimal import Decimal

from apps.api.services.ai_quote_service import _zone_request_from_extraction
from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft,
    ExtractedCargoItem,
    apply_deterministic_extraction,
)
from packages.quote_engine.oversize_config import default_oversize_pallet_rule
from packages.quote_engine.oversize_models import HandlingUnitInput
from packages.quote_engine.pallet_calculator import calculate_billing_pallets


def _draft(*items: ExtractedCargoItem, piece_count: int | None = None) -> AIExtractedQuoteDraft:
    total_weight = sum((item.weight_kg or Decimal("0")) * item.quantity for item in items)
    total_cbm = sum(
        (
            item.cbm
            if item.cbm is not None
            else (
                item.length_cm * item.width_cm * item.height_cm / Decimal("1000000")
                if item.length_cm is not None and item.width_cm is not None and item.height_cm is not None
                else Decimal("0")
            )
        )
        * item.quantity
        for item in items
    )
    return AIExtractedQuoteDraft(
        postal_code="L4K 2N2",
        city="Concord",
        province="ON",
        cbm=total_cbm or Decimal("1"),
        weight_kg=total_weight or Decimal("1"),
        piece_count=piece_count or sum(item.quantity for item in items),
        packaging_type="wooden_crate",
        address_type="commercial",
        cargo_items=list(items),
        missing_fields=[],
    )


def test_complete_oversize_cargo_item_maps_to_physical_handling_unit_and_three_pallets() -> None:
    extraction = _draft(
        ExtractedCargoItem(
            quantity=1,
            length_cm=Decimal("200"),
            width_cm=Decimal("130"),
            height_cm=Decimal("100"),
            weight_kg=Decimal("900"),
            contained_customer_pieces=1,
            source_span="1 wooden crate 200x130x100cm 900kg",
        )
    )

    request = _zone_request_from_extraction(extraction)
    assert isinstance(request.handling_units[0], HandlingUnitInput)
    unit = request.handling_units[0]
    assert unit.length_cm == Decimal("200")
    assert unit.width_cm == Decimal("130")
    assert unit.unit_weight_kg == Decimal("900")
    result = calculate_billing_pallets(
        request.handling_units,
        default_oversize_pallet_rule(),
        declared_customer_piece_count=request.piece_count,
        declared_total_weight_kg=request.weight_kg,
        declared_total_volume_cbm=request.cbm,
    )
    assert result.billing_pallets == 3
    assert not result.manual_review_required


def test_273_by_100_cargo_item_maps_to_three_pallets_without_piece_multiplier() -> None:
    extraction = _draft(
        ExtractedCargoItem(
            quantity=1,
            length_cm=Decimal("273"),
            width_cm=Decimal("100"),
            height_cm=Decimal("100"),
            weight_kg=Decimal("500"),
        )
    )

    request = _zone_request_from_extraction(extraction)
    result = calculate_billing_pallets(
        request.handling_units,
        default_oversize_pallet_rule(),
        declared_customer_piece_count=36,
        declared_total_weight_kg=Decimal("500"),
        declared_total_volume_cbm=Decimal("2.73"),
    )
    assert result.billing_pallets == 3
    assert result.components["total_size_pallets"] == 3
    assert result.components["explicit_pallet_count"] == 0


def test_aggregate_remainder_is_retained_and_routes_to_manual_without_fabricated_dimensions() -> None:
    extraction = _draft(
        ExtractedCargoItem(
            quantity=7,
            length_cm=Decimal("273"),
            width_cm=Decimal("100"),
            height_cm=Decimal("100"),
            weight_kg=Decimal("300"),
            source_span="7 long crates 273x100x100cm 300kg",
        ),
        ExtractedCargoItem(
            quantity=29,
            source_span="36 customer boxes in total",
        ),
        piece_count=36,
    )

    request = _zone_request_from_extraction(extraction)
    assert isinstance(request.handling_units[0], HandlingUnitInput)
    assert isinstance(request.handling_units[1], dict)
    assert request.handling_units[1]["length_cm"] is None
    assert request.handling_units[1]["unit_weight_kg"] is None
    result = calculate_billing_pallets(
        request.handling_units,
        default_oversize_pallet_rule(),
        declared_customer_piece_count=36,
        declared_total_weight_kg=Decimal("2100"),
        declared_total_volume_cbm=Decimal("2.73"),
    )
    assert result.manual_review_required
    assert result.billing_pallets == 21
    assert "handling_unit_dimensions_missing" in result.risk_tags
    assert "handling_unit_weight_missing" in result.risk_tags


def test_deterministic_parser_keeps_aggregate_summary_without_inventing_dimensions() -> None:
    draft = apply_deterministic_extraction(
        AIExtractedQuoteDraft(confidence=0),
        "QTY: 36 boxes / GW: 2100kg / MEAS: 20 CBM",
    )

    assert draft.cargo_items
    item = draft.cargo_items[0]
    assert item.quantity == 36
    assert item.length_cm is None
    assert item.width_cm is None
    assert item.height_cm is None
    assert item.weight_kg == Decimal("58.33")
    request = _zone_request_from_extraction(
        draft.model_copy(
            update={
                "postal_code": "L4K 2N2",
                "address_type": "commercial",
                "packaging_type": "carton",
            }
        )
    )
    assert isinstance(request.handling_units[0], dict)
    assert request.handling_units[0]["length_cm"] is None


def test_explicit_total_boxes_and_long_subset_keep_long_quantity_separate() -> None:
    draft = apply_deterministic_extraction(
        AIExtractedQuoteDraft(confidence=0),
        "36 boxes\n7 long pieces 273x100x100cm 300kg",
    )

    assert draft.piece_count == 36
    assert [item.quantity for item in draft.cargo_items] == [7, 29]
    assert draft.cargo_items[0].length_cm == Decimal("273.0")
    assert draft.cargo_items[1].length_cm is None

    request = _zone_request_from_extraction(
        draft.model_copy(
            update={
                "postal_code": "L4K 2N2",
                "address_type": "commercial",
                "packaging_type": "wooden_crate",
            }
        )
    )
    result = calculate_billing_pallets(
        request.handling_units,
        default_oversize_pallet_rule(),
        declared_customer_piece_count=36,
        declared_total_weight_kg=draft.weight_kg,
        declared_total_volume_cbm=draft.cbm,
    )
    assert result.manual_review_required
    assert result.billing_pallets == 21
    assert result.billing_pallets != 36 * 3


def test_explicit_stack_fields_and_rotation_are_passed_only_when_present() -> None:
    extraction = _draft(
        ExtractedCargoItem(
            quantity=1,
            length_cm=Decimal("120"),
            width_cm=Decimal("100"),
            height_cm=Decimal("180"),
            weight_kg=Decimal("400"),
            stackability="stackable",
            max_stack_layers=2,
            max_top_load_kg=Decimal("300"),
            floor_rotation_allowed=False,
        )
    )
    request = _zone_request_from_extraction(extraction)
    unit = request.handling_units[0]
    assert isinstance(unit, HandlingUnitInput)
    assert unit.stackability == "stackable"
    assert unit.max_stack_layers == 2
    assert unit.max_top_load_kg == Decimal("300")
    assert unit.floor_rotation_allowed is False
