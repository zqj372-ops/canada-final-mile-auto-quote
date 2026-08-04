from decimal import Decimal

from packages.quote_engine.fcl import FCLContainerInput, FCLFeeLine, FCLQuoteConfig, FCLQuoteDraft, calculate_fcl_quote


def draft() -> FCLQuoteDraft:
    return FCLQuoteDraft(
        pol="CNSHA",
        pod="CAVAN",
        containers=[
            FCLContainerInput(container_type="20GP", quantity=1),
            FCLContainerInput(container_type="40HQ", quantity=1),
        ],
        cargo_items=[{"quantity": 1, "length": 100, "width": 100, "height": 100, "weight_kg": 1000}],
        service_scope="port-to-port",
        target_etd="2026-08-10",
    )


def card(container_type: str, lines: list[dict[str, object]]) -> dict[str, object]:
    return {"id": container_type, "pol": "CNSHA", "pod": "CAVAN", "container_type": container_type, "service_scope": "port-to-port", "status": "published", "effective_from": "2026-01-01", "effective_to": "2026-12-31", "priority": 100, "enabled": True, "fee_lines": lines}


def test_kg_amount_is_rounded_after_multiplication():
    result, _ = calculate_fcl_quote(
        draft().model_copy(update={"containers": [FCLContainerInput(container_type="20GP", quantity=1)]}),
        FCLQuoteConfig(required_fields=[]),
        [card("20GP", [FCLFeeLine(item_name="重量费", fee_id="weight", scope="per_kg", unit="kg", currency="USD", sales_unit_price=Decimal("0.005")).model_dump(mode="json")])],
        quote_id="q-fee-1",
        config_version=1,
    )
    assert result.totals_by_currency == {"USD": Decimal("5.00")}


def test_per_shipment_fee_is_deduplicated_across_container_cards():
    lines = [FCLFeeLine(item_name="文件费", fee_id="docs", scope="per_shipment", unit="shipment", currency="USD", sales_unit_price=Decimal("10")).model_dump(mode="json")]
    result, _ = calculate_fcl_quote(
        draft(),
        FCLQuoteConfig(required_fields=[]),
        [card("20GP", lines), card("40HQ", lines)],
        quote_id="q-fee-2",
        config_version=1,
    )
    assert result.totals_by_currency == {"USD": Decimal("10.00")}


def test_fixed_markup_is_one_quote_level_fee():
    result, _ = calculate_fcl_quote(
        draft().model_copy(update={"containers": [FCLContainerInput(container_type="20GP", quantity=1)]}),
        FCLQuoteConfig(required_fields=[], markup_fixed=Decimal("25"), settlement_currency="USD"),
        [card("20GP", [FCLFeeLine(item_name="海运费", fee_id="ocean", unit="container", currency="USD", sales_unit_price=Decimal("100")).model_dump(mode="json")])],
        quote_id="q-fee-3",
        config_version=1,
    )
    assert result.totals_by_currency == {"USD": Decimal("125.00")}
    assert [item.item_name for item in result.fee_items].count("固定加价（每票）") == 1
