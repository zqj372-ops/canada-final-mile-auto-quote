from apps.api.services.quote_logic_explainer import build_zone_quote_logic
from packages.quote_engine.zone_engine import build_zone_price_disabled_reason


def test_zone_price_disabled_reason_separates_destination_from_origin() -> None:
    reason = build_zone_price_disabled_reason(
        city="Edmonton",
        province="AB",
        postal_code="T5T 4B2",
        origin="calgary",
        zone=9,
    )

    assert reason == "分区价格已关闭：目的地 Edmonton, AB, T5T 4B2；始发仓 卡尔加里；Zone 9。"


def test_zone_price_disabled_quote_logic_names_origin_as_warehouse() -> None:
    logic = build_zone_quote_logic(
        {"piece_count": 1, "cbm": 1, "weight_kg": 100},
        {
            "manual_review_required": True,
            "source_type": "manual_required",
            "origin": "calgary",
            "zone": 9,
            "billing_pallets": 1,
            "postal_prefix": "T5T",
            "postal_code": "T5T 4B2",
            "city": "Edmonton",
            "province": "AB",
            "matched_rule": "分区价格已关闭：目的地 Edmonton, AB, T5T 4B2；始发仓 卡尔加里；Zone 9。",
            "risk_tags": ["zone_price_disabled"],
            "match_trace": {},
        },
    )

    assert (
        "目的地 Edmonton, AB, T5T 4B2 已命中 卡尔加里 始发仓 Zone 9"
        in logic["next_action"]
    )
