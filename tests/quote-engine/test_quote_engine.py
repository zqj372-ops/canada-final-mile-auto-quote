from decimal import Decimal

from packages.quote_engine import QuoteCalculationRequest, QuoteEngine, RateRule, ShipmentInput, SourceType


def test_fsa_match_calculates_deterministic_quote() -> None:
    request = QuoteCalculationRequest(
        shipment=ShipmentInput(
            postal_code="L5T 2X3",
            city="Mississauga",
            province="Ontario",
            origin_warehouse="Toronto",
            pallet_count=3,
            requires_appointment=True,
            dock_available=None,
            target_margin_percent=Decimal("0.25"),
        ),
        rate_rules=[
            RateRule(
                rule_id="sample-fsa",
                source_type=SourceType.FSA,
                origin_warehouse="Toronto",
                province="ON",
                city="Mississauga",
                fsa="L5T",
                pallet_min=1,
                pallet_max=5,
                base_cost_cad=Decimal("100.00"),
                fuel_percent=Decimal("10"),
                appointment_fee_cad=Decimal("15.00"),
            )
        ],
    )

    result = QuoteEngine().quote(request)

    assert result.source_type == SourceType.FSA
    assert result.confidence == 80
    assert result.internal_cost_cad == Decimal("125.00")
    assert result.suggested_selling_price_cad == Decimal("166.67")
    assert "appointment_required" in result.risk_tags
    assert result.manual_review_required is False


def test_postal_code_priority_wins_over_fsa() -> None:
    request = QuoteCalculationRequest(
        shipment=ShipmentInput(postal_code="L5T 2X3", province="ON", pallet_count=1),
        rate_rules=[
            RateRule(
                rule_id="sample-fsa",
                source_type=SourceType.FSA,
                fsa="L5T",
                province="ON",
                pallet_min=1,
                pallet_max=5,
                base_cost_cad=Decimal("100.00"),
            ),
            RateRule(
                rule_id="sample-postal",
                source_type=SourceType.POSTAL_CODE,
                postal_code="L5T 2X3",
                province="ON",
                pallet_min=1,
                pallet_max=5,
                base_cost_cad=Decimal("120.00"),
            ),
        ],
    )

    result = QuoteEngine().quote(request)

    assert result.source_type == SourceType.POSTAL_CODE
    assert result.matched_rule.startswith("postal_code")


def test_no_match_returns_manual_required_without_price() -> None:
    request = QuoteCalculationRequest(
        shipment=ShipmentInput(postal_code="L5T 2X3", province="ON", pallet_count=1),
        rate_rules=[],
    )

    result = QuoteEngine().quote(request)

    assert result.source_type == SourceType.MANUAL_REQUIRED
    assert result.manual_review_required is True
    assert result.internal_cost_cad is None
    assert result.suggested_selling_price_cad is None


def test_weight_bound_rule_requires_matching_weight() -> None:
    request = QuoteCalculationRequest(
        shipment=ShipmentInput(postal_code="L5T 2X3", province="ON", pallet_count=1, weight_kg=Decimal("850")),
        rate_rules=[
            RateRule(
                rule_id="too-light",
                source_type=SourceType.FSA,
                fsa="L5T",
                province="ON",
                pallet_min=1,
                pallet_max=5,
                weight_max_kg=Decimal("100.00"),
                base_cost_cad=Decimal("100.00"),
            )
        ],
    )

    result = QuoteEngine().quote(request)

    assert result.source_type == SourceType.MANUAL_REQUIRED
