from datetime import date, timedelta
from decimal import Decimal

from packages.quote_engine.fcl import (
    FCLCargoItem,
    FCLContainerInput,
    FCLFeeLine,
    FCLQuoteConfig,
    FCLQuoteDraft,
    calculate_cargo,
    calculate_fcl_quote,
)


def rate_card(card_id: int, *, priority: int = 100, fee_lines: list[dict[str, object]] | None = None, **overrides: object) -> dict[str, object]:
    return {
        "id": card_id,
        "pol": "CNSHA",
        "pod": "CAVAN",
        "container_type": "40HQ",
        "carrier": None,
        "service": None,
        "service_scope": "port-to-port",
        "effective_from": date.today() - timedelta(days=1),
        "effective_to": date.today() + timedelta(days=30),
        "etd_date": None,
        "vessel_voyage": None,
        "priority": priority,
        "source": "test",
        "status": "published",
        "enabled": True,
        "fee_lines": fee_lines
        or [
            {
                "item_name": "海运费",
                "unit": "container",
                "currency": "USD",
                "sales_unit_price": "100.005",
                "pricing_status": "auto",
                "display_mode": "both",
                "include_in_quote": True,
            }
        ],
        **overrides,
    }


def base_draft(**overrides: object) -> FCLQuoteDraft:
    values: dict[str, object] = {
        "customer_name": "ABC Trading Ltd.",
        "contact": "张三 / zhang@example.com",
        "customer_type": "importer",
        "pol": "Shanghai",
        "pod": "Vancouver",
        "containers": [FCLContainerInput(container_type="40HC", quantity=2)],
        "cargo_name": "sample",
        "cargo_items": [
            FCLCargoItem(
                name="sample",
                quantity=2,
                length=Decimal("100"),
                width=Decimal("50"),
                height=Decimal("50"),
                dimension_unit="cm",
                weight=Decimal("100"),
                weight_unit="lb",
            )
        ],
        "special_attributes": ["general_cargo"],
        "ready_date": date.today(),
        "importer_exists": "yes",
        "service_scope": "port-to-port",
    }
    values.update(overrides)
    return FCLQuoteDraft(**values)


def test_cargo_recalculation_uses_dimensions_and_converts_pounds() -> None:
    result = calculate_cargo(base_draft())

    assert result.piece_count == 2
    assert result.total_volume_cbm == Decimal("0.500")
    assert result.total_weight_kg == Decimal("90.72")
    assert "volume_from_dimensions" in result.calculation_basis
    assert "weight_from_items" in result.calculation_basis


def test_fcl_quote_calculates_container_and_shipment_lines_with_decimal() -> None:
    config = FCLQuoteConfig(
        markup_percent=Decimal("10"),
        port_aliases={"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
        container_aliases={"40HC": "40HQ"},
    )
    cards = [
        rate_card(
            1,
            fee_lines=[
                {
                    "item_name": "海运费",
                    "unit": "container",
                    "currency": "USD",
                    "sales_unit_price": "100.005",
                    "pricing_status": "auto",
                    "display_mode": "both",
                    "include_in_quote": True,
                },
                {
                    "item_name": "文件费",
                    "unit": "shipment",
                    "currency": "CAD",
                    "cost_unit_price": "10",
                    "pricing_status": "auto",
                    "display_mode": "both",
                    "include_in_quote": True,
                },
                {
                    "item_name": "目的港隐藏包含",
                    "unit": "shipment",
                    "currency": "CNY",
                    "sales_unit_price": "5",
                    "pricing_status": "auto",
                    "display_mode": "hiddenIncluded",
                    "include_in_quote": True,
                },
            ],
        )
    ]

    result, snapshot = calculate_fcl_quote(
        base_draft(),
        config,
        cards,
        quote_id="fcl_test",
        config_version=3,
    )

    assert result.manual_review_required is False
    assert result.totals_by_currency == {"CAD": Decimal("11.00"), "CNY": Decimal("5.00"), "USD": Decimal("200.02")}
    assert result.fee_items[0].amount == Decimal("200.02")
    assert result.fee_items[2].amount is None
    assert snapshot["config_version"] == 3
    assert snapshot["fee_items"][0]["cost_unit_price"] is None


def test_fcl_quote_fails_closed_for_conflict_expiry_and_ambiguous_priority() -> None:
    config = FCLQuoteConfig(
        port_aliases={"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
        container_aliases={"40HC": "40HQ"},
    )
    conflict = base_draft(declared_total_volume_cbm=Decimal("99"))
    result, _ = calculate_fcl_quote(conflict, config, [rate_card(1)], quote_id="fcl_conflict", config_version=1)
    assert result.manual_review_required is True
    assert "declared_total_volume_conflict" in result.manual_reasons
    assert result.totals_by_currency == {}

    expired = rate_card(2, effective_to=date.today() - timedelta(days=1))
    result, _ = calculate_fcl_quote(base_draft(), config, [expired], quote_id="fcl_expired", config_version=1)
    assert result.manual_review_required is True
    assert "no_published_rate_card:40HQ" in result.manual_reasons

    result, _ = calculate_fcl_quote(base_draft(), config, [rate_card(3), rate_card(4)], quote_id="fcl_ambiguous", config_version=1)
    assert result.manual_review_required is True
    assert any(reason.startswith("ambiguous_rate_cards:40HQ") for reason in result.manual_reasons)


def test_actual_fee_never_enters_auto_total() -> None:
    config = FCLQuoteConfig(
        port_aliases={"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
        container_aliases={"40HC": "40HQ"},
    )
    result, _ = calculate_fcl_quote(
        base_draft(),
        config,
        [rate_card(1, fee_lines=[
            FCLFeeLine(item_name="实报实销", unit="shipment", currency="CAD", pricing_status="actual").model_dump(mode="json")
        ])],
        quote_id="fcl_actual",
        config_version=1,
    )
    assert result.manual_review_required is True
    assert result.totals_by_currency == {}
    assert any(reason == "manual_fee:实报实销" for reason in result.manual_reasons)


def test_cargo_value_requires_currency() -> None:
    config = FCLQuoteConfig(
        port_aliases={"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
        container_aliases={"40HC": "40HQ"},
    )
    result, _ = calculate_fcl_quote(
        base_draft(cargo_value=Decimal("15000")),
        config,
        [rate_card(1)],
        quote_id="fcl_value_currency",
        config_version=1,
    )
    assert result.manual_review_required is True
    assert "missing:cargo_value_currency" in result.manual_reasons
