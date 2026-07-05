from decimal import Decimal

from packages.ai_assistant import build_ai_context, validate_ai_output, validate_zone_ai_output
from packages.quote_engine.models import QuoteResult, SourceType
from packages.quote_engine.zone_models import ZoneQuoteResult, ZoneQuoteSourceType


def test_guard_allows_locked_quote_amounts() -> None:
    result = QuoteResult(
        source_type=SourceType.FSA,
        confidence=80,
        matched_rule="fsa + ON + L5T + 3 pallets",
        internal_cost_cad=Decimal("125.00"),
        suggested_selling_price_cad=Decimal("166.67"),
        margin_cad=Decimal("41.67"),
        margin_percent=Decimal("0.25"),
        cost_breakdown={"base_cost": Decimal("100.00"), "fuel": Decimal("10.00")},
        risk_tags=["dock_unknown"],
        manual_review_required=False,
    )

    context = build_ai_context(result)
    guard = validate_ai_output(context, "Customer quote is CAD 166.67. Dock status should be confirmed.")

    assert guard.allowed is True


def test_guard_blocks_new_money_amounts() -> None:
    result = QuoteResult(
        source_type=SourceType.FSA,
        confidence=80,
        matched_rule="fsa + ON + L5T + 3 pallets",
        internal_cost_cad=Decimal("125.00"),
        suggested_selling_price_cad=Decimal("166.67"),
        margin_cad=Decimal("41.67"),
        margin_percent=Decimal("0.25"),
        cost_breakdown={},
        risk_tags=[],
        manual_review_required=False,
    )

    context = build_ai_context(result)
    guard = validate_ai_output(context, "Customer quote is CAD 199.00.")

    assert guard.allowed is False
    assert "not in quote_result" in (guard.reason or "")


def test_zone_guard_blocks_unauthorized_sales_note_amount() -> None:
    result = ZoneQuoteResult(
        source_type=ZoneQuoteSourceType.ZONE_MATRIX,
        confidence=90,
        base_price_usd=Decimal("120.00"),
        fuel_usd=Decimal("42.00"),
        accessorials={"appointment_fee_usd": Decimal("50.00")},
        total_price_usd=Decimal("212.00"),
        risk_tags=[],
        manual_review_required=False,
        matched_rule="zone_matrix + test",
    )

    guard = validate_zone_ai_output(result, "Customer quote is $999.00 USD.")

    assert guard.allowed is False
    assert "not in quote_result" in (guard.reason or "")


def test_zone_guard_blocks_manual_required_definite_amount() -> None:
    result = ZoneQuoteResult(
        source_type=ZoneQuoteSourceType.MANUAL_REQUIRED,
        confidence=0,
        risk_tags=["zone_not_found"],
        manual_review_required=True,
        matched_rule="No zone matched.",
    )

    guard = validate_zone_ai_output(result, "报价为 $212.00 USD")

    assert guard.allowed is False
    assert "manual review" in (guard.reason or "")
