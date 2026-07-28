from decimal import Decimal

from packages.quote_engine.zone_models import ZoneQuoteResult, ZoneQuoteSourceType
from scripts.reconcile_manual_zone_tasks import (
    mark_cancelled_reconciliation,
    require_exact_match_before_cancelling,
)


def _quoted_result(*, matched_by: str) -> ZoneQuoteResult:
    return ZoneQuoteResult(
        source_type=ZoneQuoteSourceType.ZONE_MATRIX,
        confidence=90,
        postal_code="V4C 6J7",
        postal_prefix="V4C",
        city="Delta",
        province="BC",
        origin="calgary",
        zone=5,
        billing_pallets=1,
        base_price_usd=Decimal("100.00"),
        fuel_usd=Decimal("35.00"),
        total_price_usd=Decimal("135.00"),
        manual_review_required=False,
        matched_rule="test",
        matched_by=matched_by,
        match_trace={
            "input_city": "Delta",
            "matched_rule_city": "DELTA",
            "matched_rule_match_level": "manual_correction",
        },
    )


def test_exact_fsa_requote_can_cancel_historical_manual_task() -> None:
    result = _quoted_result(matched_by="fsa_single_zone")

    reconciled = require_exact_match_before_cancelling(result)

    assert reconciled is result
    assert reconciled.manual_review_required is False


def test_city_fallback_requote_stays_manual_and_clears_price() -> None:
    result = _quoted_result(matched_by="city_zone_fallback")

    reconciled = require_exact_match_before_cancelling(result)

    assert reconciled.source_type == ZoneQuoteSourceType.MANUAL_REQUIRED
    assert reconciled.manual_review_required is True
    assert reconciled.matched_by == "historical_task_non_exact_recheck"
    assert "historical_task_non_exact_recheck" in reconciled.risk_tags
    assert reconciled.base_price_usd is None
    assert reconciled.total_price_usd is None
    assert reconciled.match_trace["recomputed_matched_by"] == "city_zone_fallback"


def test_untrusted_or_city_conflicting_exact_fsa_stays_manual() -> None:
    untrusted = _quoted_result(matched_by="fsa_single_zone").model_copy(
        update={
            "match_trace": {
                "input_city": "Delta",
                "matched_rule_city": "DELTA",
                "matched_rule_match_level": "L1",
            }
        }
    )
    conflicting_city = _quoted_result(matched_by="fsa_single_zone").model_copy(
        update={
            "match_trace": {
                "input_city": "Delta",
                "preferred_city": "New Westminster",
                "matched_rule_city": "NEW WESTMINSTER",
                "matched_rule_match_level": "manual_correction",
            },
            "preferred_city": "New Westminster",
            "city": "New Westminster",
        }
    )

    assert require_exact_match_before_cancelling(untrusted).manual_review_required is True
    assert require_exact_match_before_cancelling(conflicting_city).manual_review_required is True


def test_exact_fsa_with_other_manual_blocker_stays_manual() -> None:
    result = _quoted_result(matched_by="fsa_single_zone").model_copy(
        update={"risk_tags": ["ai_missing_fields"]}
    )

    reconciled = require_exact_match_before_cancelling(result)

    assert reconciled.manual_review_required is True
    assert reconciled.match_trace["blocking_non_zone_risk_tags"] == ["ai_missing_fields"]


def test_cancelled_reconciliation_never_says_result_can_be_sent_to_customer() -> None:
    result = _quoted_result(matched_by="fsa_single_zone").model_copy(
        update={
            "match_trace": {
                "matched_rule_city": "DELTA",
                "quote_logic": {"next_action": "可发客户"},
            },
            "sales_note": "客户版报价",
        }
    )

    reconciled = mark_cancelled_reconciliation(result)

    quote_logic = reconciled.match_trace["quote_logic"]
    assert "可发客户" not in quote_logic["next_action"]
    assert "禁止直接发送" in quote_logic["next_action"]
    assert "未发送客户" in reconciled.sales_note
