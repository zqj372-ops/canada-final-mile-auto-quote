from decimal import Decimal
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import (
    Base,
    CityAlias,
    PostalCodeCityLookup,
    PostalZoneOverride,
    QuoteRuleConfig,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.session import get_db
from apps.api.main import app


def build_client(
    *,
    postal_records: list[dict[str, object]] | None = None,
    postal_overrides: list[dict[str, object]] | None = None,
    city_aliases: list[dict[str, object]] | None = None,
    zone_rules: list[dict[str, object]] | None = None,
    prices: list[dict[str, object]] | None = None,
    quote_rule_configs: list[dict[str, object]] | None = None,
) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        for record in postal_records or default_postal_records():
            session.add(PostalCodeCityLookup(**record))
        for record in postal_overrides or []:
            session.add(PostalZoneOverride(**record))
        for record in city_aliases or []:
            session.add(CityAlias(**record))
        for record in zone_rules or default_zone_rules():
            session.add(ZoneLookupRule(**record))
        for record in prices or default_prices():
            session.add(ZonePriceMatrix(**record))
        for record in quote_rule_configs or []:
            session.add(QuoteRuleConfig(**record))
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def default_postal_records() -> list[dict[str, object]]:
    return [
        {"postal_code": "L4K 2N2", "preferred_city": "Concord", "province": "ON"},
        {"postal_code": "V6V 1A1", "preferred_city": "Richmond", "province": "BC"},
        {"postal_code": "T1X 0A0", "preferred_city": "Calgary", "province": "AB"},
    ]


def default_zone_rules() -> list[dict[str, object]]:
    return [
        {
            "postal_prefix": "L4K",
            "city": "CONCORD",
            "province": "ON",
            "origin": "toronto",
            "zone": 2,
            "match_level": "demo",
            "note": "",
        },
        {
            "postal_prefix": "V6V",
            "city": "RICHMOND",
            "province": "BC",
            "origin": "toronto",
            "zone": 5,
            "match_level": "demo",
            "note": "stale origin demo",
        },
        {
            "postal_prefix": "T1X",
            "city": "CALGARY",
            "province": "AB",
            "origin": "calgary",
            "zone": 1,
            "match_level": "demo",
            "note": "",
        },
        {
            "postal_prefix": "T1X",
            "city": "CALGARY",
            "province": "AB",
            "origin": "toronto",
            "zone": 9,
            "match_level": "demo",
            "note": "split demo",
        },
    ]


def default_prices() -> list[dict[str, object]]:
    return [
        {
            "origin": "toronto",
            "zone": 2,
            "billing_pallets": 1,
            "base_price_usd": Decimal("90.00"),
            "source": "test",
            "last_updated": "2026-06-03",
        },
        {
            "origin": "toronto",
            "zone": 2,
            "billing_pallets": 2,
            "base_price_usd": Decimal("105.00"),
            "source": "test",
            "last_updated": "2026-06-03",
        },
        {
            "origin": "toronto",
            "zone": 2,
            "billing_pallets": 3,
            "base_price_usd": Decimal("120.00"),
            "source": "test",
            "last_updated": "2026-06-03",
        },
        {
            "origin": "toronto",
            "zone": 2,
            "billing_pallets": 4,
            "base_price_usd": Decimal("135.00"),
            "source": "test",
            "last_updated": "2026-06-03",
        },
        {
            "origin": "calgary",
            "zone": 1,
            "billing_pallets": 3,
            "base_price_usd": Decimal("95.00"),
            "source": "test",
            "last_updated": "2026-06-03",
        },
        {
            "origin": "calgary",
            "zone": 5,
            "billing_pallets": 3,
            "base_price_usd": Decimal("180.00"),
            "source": "test",
            "last_updated": "2026-06-03",
        },
    ]


def base_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "address_line": "8888 Keele St",
        "postal_code": "L4K 2N2",
        "city": "Concord",
        "province": "ON",
        "cbm": 4.2,
        "weight_kg": 850,
        "piece_count": 10,
        "packaging_type": "carton",
        "longest_side_cm": 100,
        "address_type": "commercial",
        "requires_liftgate": False,
        "requires_pallet_jack": False,
        "requires_appointment": True,
        "explicit_pallet_count": None,
    }
    payload.update(overrides)
    return payload


def test_l4k_concord_on_zone_quote_success() -> None:
    client = build_client()

    response = client.post("/quotes/zone-calculate", json=base_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["confidence"] == 90
    assert body["matched_by"] == "fsa_single_zone"
    assert body["candidate_count"] == 1
    assert body["match_trace"]["fsa"] == "L4K"
    assert body["origin"] == "toronto"
    assert body["zone"] == 2
    assert body["billing_pallets"] == 3
    assert body["base_price_usd"] == "120.00"
    assert body["fuel_usd"] == "42.00"
    assert body["accessorials"]["appointment_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False
    assert "rural_fsa_secondary_confirmation" not in body["risk_tags"]


def test_rural_postal_quote_keeps_price_but_requires_secondary_confirmation() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "T0B 3L0", "preferred_city": "Mundare", "province": "AB"},
        ],
        zone_rules=[
            {
                "postal_prefix": "T0B",
                "city": "MUNDARE",
                "province": "AB",
                "origin": "calgary",
                "zone": 1,
                "match_level": "test",
                "note": "",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="5008 50 St",
            postal_code="T0B 3L0",
            city="Mundare",
            province="AB",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["manual_review_required"] is False
    assert body["total_price_usd"] == "128.25"
    assert "rural_fsa_secondary_confirmation" in body["risk_tags"]
    assert "二次确认：该地址为乡村邮编" in body["sales_note"]


def test_city_postal_zone_conflict_explains_both_candidates() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "N0A 1M0", "preferred_city": "Ohsweken", "province": "ON"},
        ],
        zone_rules=[
            {
                "postal_prefix": "N0A",
                "city": "HAGERSVILLE",
                "province": "ON",
                "origin": "toronto",
                "zone": 5,
                "match_level": "test",
                "note": "",
            },
            {
                "postal_prefix": "N0A",
                "city": "OHSWEKEN",
                "province": "ON",
                "origin": "toronto",
                "zone": 6,
                "match_level": "test",
                "note": "",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="1595 Sour Springs Rd",
            postal_code="N0A 1M0",
            city="Hagersville",
            province="ON",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "split_record_conflict"
    assert body["manual_review_required"] is True
    assert body["matched_rule"] == (
        "地址信息对应不同 Zone：输入城市 Hagersville → 多伦多 Zone 5；"
        "邮编 N0A 1M0 对应城市 Ohsweken → 多伦多 Zone 6。请核对城市或邮编后再报价。"
    )
    assert "rural_fsa_secondary_confirmation" in body["risk_tags"]


def test_zone_quote_uses_zone_fuel_percent_override() -> None:
    client = build_client(
        quote_rule_configs=[
            {
                "key": "fuel_percent_by_zone",
                "value": '{"calgary|1":"10"}',
                "description": None,
            }
        ]
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="123 Calgary Trail",
            postal_code="T1X 0A0",
            city="Calgary",
            province="AB",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["origin"] == "calgary"
    assert body["zone"] == 1
    assert body["base_price_usd"] == "95.00"
    assert body["fuel_usd"] == "9.50"
    assert body["total_price_usd"] == "104.50"


def test_zone_8_price_is_disabled_by_default_even_when_matrix_has_a_price() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V8V 1A1", "preferred_city": "Victoria", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V8V",
                "city": "VICTORIA",
                "province": "BC",
                "origin": "calgary",
                "zone": 8,
                "match_level": "test",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 8,
                "billing_pallets": 3,
                "base_price_usd": Decimal("380.00"),
                "source": "test",
                "last_updated": "2026-07-20",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="100 Victoria Street",
            postal_code="V8V 1A1",
            city="Victoria",
            province="BC",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "zone_price_disabled"
    assert body["origin"] == "calgary"
    assert body["zone"] == 8
    assert body["base_price_usd"] is None
    assert body["fuel_usd"] is None
    assert body["total_price_usd"] is None
    assert body["manual_review_required"] is True
    assert "zone_price_disabled" in body["risk_tags"]


def test_disabled_zone_price_reason_separates_destination_from_origin() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "T5T 4B2", "preferred_city": "Edmonton", "province": "AB"},
        ],
        zone_rules=[
            {
                "postal_prefix": "T5T",
                "city": "EDMONTON",
                "province": "AB",
                "origin": "calgary",
                "zone": 9,
                "match_level": "test",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 9,
                "billing_pallets": 3,
                "base_price_usd": Decimal("460.00"),
                "source": "test",
                "last_updated": "2026-07-21",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="20627 93Ave NW",
            postal_code="T5T 4B2",
            city="Edmonton",
            province="AB",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "zone_price_disabled"
    assert body["city"] == "Edmonton"
    assert body["province"] == "AB"
    assert body["origin"] == "calgary"
    assert body["zone"] == 9
    assert body["matched_rule"] == "分区价格已关闭：目的地 Edmonton, AB, T5T 4B2；始发仓 卡尔加里；Zone 9。"
    logic_steps = body["match_trace"]["quote_logic"]["steps"]
    assert any("目的地 Edmonton, AB, T5T 4B2 已命中 卡尔加里 始发仓 Zone 9" in step for step in logic_steps)
    assert "zone_price_disabled" in body["risk_tags"]


def test_zone_8_price_can_be_explicitly_enabled() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V8V 1A1", "preferred_city": "Victoria", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V8V",
                "city": "VICTORIA",
                "province": "BC",
                "origin": "calgary",
                "zone": 8,
                "match_level": "test",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 8,
                "billing_pallets": 3,
                "base_price_usd": Decimal("380.00"),
                "source": "test",
                "last_updated": "2026-07-20",
            },
        ],
        quote_rule_configs=[
            {
                "key": "zone_price_enabled_by_zone",
                "value": '{"calgary|8":true}',
                "description": None,
            }
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="100 Victoria Street",
            postal_code="V8V 1A1",
            city="Victoria",
            province="BC",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["origin"] == "calgary"
    assert body["zone"] == 8
    assert body["base_price_usd"] == "380.00"
    assert body["total_price_usd"] == "513.00"
    assert body["manual_review_required"] is False


def test_zone_1_price_can_be_explicitly_disabled() -> None:
    client = build_client(
        quote_rule_configs=[
            {
                "key": "zone_price_enabled_by_zone",
                "value": '{"calgary|1":false}',
                "description": None,
            }
        ]
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="123 Calgary Trail",
            postal_code="T1X 0A0",
            city="Calgary",
            province="AB",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "zone_price_disabled"
    assert body["origin"] == "calgary"
    assert body["zone"] == 1
    assert body["total_price_usd"] is None
    assert "zone_price_disabled" in body["risk_tags"]


def test_global_zone_price_switch_disables_an_enabled_low_zone() -> None:
    client = build_client(
        quote_rule_configs=[
            {
                "key": "zone_price_enabled",
                "value": "false",
                "description": None,
            }
        ]
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="123 Calgary Trail",
            postal_code="T1X 0A0",
            city="Calgary",
            province="AB",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "zone_price_disabled"
    assert body["zone"] == 1
    assert body["total_price_usd"] is None
    assert "zone_price_disabled" in body["risk_tags"]


def test_invalid_postal_code_returns_one_focused_validation_error() -> None:
    client = build_client()

    response = client.post("/quotes/zone-calculate", json=base_payload(postal_code="not-a-postal-code"))

    assert response.status_code == 422
    details = response.json()["detail"]
    assert len(details) == 1
    assert details[0]["loc"][-2:] == ["quote", "postal_code"]
    assert details[0]["msg"] == "Value error, postal_code must be a valid Canadian postal code"


def test_sales_note_uses_customer_copy_template_with_cargo_totals() -> None:
    client = build_client()

    response = client.post("/quotes/zone-calculate", json=base_payload(requires_appointment=False))

    body = response.json()
    sales_note = body["sales_note"]
    assert "加拿大尾端派送报价：" in sales_note
    assert "货物总计：共10件，4.2 CBM，850 KG，计费3托，密度202.4 KG/CBM，最长边100CM" in sales_note
    assert "报价：USD 162（多伦多派送）" in sales_note
    assert "注：不带尾板，自卸货" in sales_note
    assert "- 送货到门口路边，不含其他操作" in sales_note
    assert "- 无卸货平台需尾板 +50USD/票" in sales_note
    assert "- 需手叉车配合 +50USD/票" in sales_note
    assert "- 免费等待30分钟，超时35USD/半小时" in sales_note
    assert "- 价格以供应商实测地址及卡车准入情况为准" in sales_note
    assert "- 下单引用单号，未引用加收50人民币/票服务费" in sales_note


def test_v6v_stale_toronto_rule_cannot_be_reused_as_calgary_zone() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            postal_code="V6V 1A1",
            city="Richmond",
            province="BC",
            cbm=4.2,
            weight_kg=850,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "origin_matrix_guard"
    assert body["origin"] is None
    assert body["zone"] is None
    assert body["total_price_usd"] is None
    assert "stale_origin_overridden" in body["risk_tags"]
    assert "origin_matrix_mismatch" in body["risk_tags"]
    assert body["match_trace"]["expected_origin"] == "calgary"
    assert body["match_trace"]["rejected_zone"] == 5
    assert body["manual_review_required"] is True


def test_stale_exact_zone_uses_same_city_expected_origin_anchor() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V6V 1A1", "preferred_city": "Richmond", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V6V",
                "city": "RICHMOND",
                "province": "BC",
                "origin": "toronto",
                "zone": 10,
                "match_level": "legacy_anchor",
                "note": "stale exact FSA row",
            },
            {
                "postal_prefix": "V6W",
                "city": "RICHMOND",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "match_level": "trusted_city_anchor",
                "note": "same-city expected-origin anchor",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 3,
                "base_price_usd": Decimal("180.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            postal_code="V6V 1A1",
            city="Richmond",
            province="BC",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "city_zone_fallback"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["base_price_usd"] == "180.00"
    assert body["manual_review_required"] is False
    assert "stale_origin_overridden" not in body["risk_tags"]
    assert "expected_origin_preferred" in body["risk_tags"]


def test_city_fallback_ignores_cross_province_legacy_anchor() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V4G 1N4", "preferred_city": "Delta", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "K0E",
                "city": "DELTA",
                "province": "BC",
                "origin": "toronto",
                "zone": 10,
                "match_level": "legacy_anchor",
                "note": "K0E is an Ontario FSA, not a BC FSA",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="7939 Horne Street",
            postal_code="V4G 1N4",
            city="Delta",
            province="BC",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "city_fallback_invalid_anchor"
    assert body["origin"] is None
    assert body["zone"] is None
    assert body["total_price_usd"] is None
    assert "zone_rule_province_mismatch" in body["risk_tags"]
    assert "K0E" in body["matched_rule"]
    assert "V4G" in body["matched_rule"]
    assert "检测到无关的跨省脏记录" in body["matched_rule"]
    assert "Delta + BC 的 Zone 锚点" not in body["matched_rule"]
    assert "检测到无关的跨省脏记录" in body["match_trace"]["quote_logic"]["next_action"]


def test_white_rock_v4b_uses_corrected_calgary_zone_5() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V4B 2C5", "preferred_city": "White Rock", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V4B",
                "city": "WHITE ROCK",
                "canonical_city": "WHITE ROCK",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "priority": 10,
                "match_level": "manual_correction",
                "note": "White Rock V4B correction",
            },
            {
                "postal_prefix": "B4P",
                "city": "WHITE ROCK",
                "canonical_city": "WHITE ROCK",
                "province": "BC",
                "origin": "toronto",
                "zone": 12,
                "match_level": "legacy_anchor",
                "note": "B4P is an NS FSA and must be ignored for White Rock, BC",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 3,
                "base_price_usd": Decimal("180.00"),
                "source": "test",
                "last_updated": "2026-07-27",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="15930 Prospect Crescent",
            postal_code="V4B 2C5",
            city="White Rock",
            province="BC",
            address_type="residential",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "fsa_single_zone"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["base_price_usd"] == "180.00"
    assert body["accessorials"]["residential_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "293.00"
    assert body["manual_review_required"] is False
    assert "residential" in body["risk_tags"]
    assert "zone_rule_province_mismatch" not in body["risk_tags"]


def test_postal_province_prevents_wrong_origin_from_parser_or_address_data() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V6V 1A1", "preferred_city": "Richmond", "province": "ON"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V6V",
                "city": "RICHMOND",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "match_level": "bad_legacy_data",
                "note": "Both province and origin are wrong for a V postal code.",
            },
        ],
        prices=[
            {
                "origin": "toronto",
                "zone": 2,
                "billing_pallets": 3,
                "base_price_usd": Decimal("120.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(postal_code="V6V 1A1", city="Richmond", province="ON"),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["province"] == "BC"
    assert body["origin"] is None
    assert body["zone"] is None
    assert body["total_price_usd"] is None


def test_t1x_prefers_expected_calgary_origin_over_stale_toronto_record() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(postal_code="T1X 0A0", city=None, province=None, requires_appointment=False),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["manual_review_required"] is False
    assert body["matched_by"] == "canonical_city"
    assert body["origin"] == "calgary"
    assert body["zone"] == 1
    assert body["billing_pallets"] == 3
    assert body["base_price_usd"] == "95.00"
    assert "expected_origin_preferred" in body["risk_tags"]


def test_residential_address_adds_50_usd() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(address_type="residential", requires_appointment=False),
    )

    body = response.json()
    assert body["accessorials"]["residential_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "212.00"


def test_liftgate_adds_50_usd() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(requires_liftgate=True, requires_appointment=False),
    )

    body = response.json()
    assert body["accessorials"]["liftgate_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "212.00"


def test_appointment_adds_50_usd() -> None:
    client = build_client()

    response = client.post("/quotes/zone-calculate", json=base_payload(requires_appointment=True))

    body = response.json()
    assert body["accessorials"]["appointment_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "212.00"


def test_billing_pallets_uses_max_of_cbm_and_weight() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(cbm=1, weight_kg=1200, requires_appointment=False),
    )

    body = response.json()
    assert body["billing_pallets"] == 3
    assert body["base_price_usd"] == "120.00"


def test_hard_long_piece_over_240cm_counts_two_pallets_per_piece() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            cbm=1,
            weight_kg=100,
            piece_count=2,
            longest_side_cm=240,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["billing_pallets"] == 4
    assert body["base_price_usd"] == "135.00"


def test_suspicious_long_piece_count_requires_manual_before_price_lookup() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V5L 4X5", "preferred_city": "Vancouver", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V5L",
                "city": "VANCOUVER",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "match_level": "test",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 3,
                "base_price_usd": Decimal("180.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="1300 Stewart St",
            postal_code="V5L 4X5",
            city="Vancouver",
            province="BC",
            cbm=1.62,
            weight_kg=1340,
            piece_count=2250,
            longest_side_cm=300,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["billing_pallets"] is None
    assert body["pallet_breakdown"]["long_piece_pallets"] == 4500
    assert body["pallet_breakdown"]["normal_basis_pallets"] == 3
    assert "long_piece_count_suspicious" in body["risk_tags"]
    assert not body["matched_rule"].startswith("Zone 价格矩阵缺少价格")


def test_missing_zone_returns_manual_required() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(postal_code="L5T 2X3", city="Mississauga", province="ON"),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["billing_pallets"] == 3
    assert body["pallet_breakdown"]["volume_pallets"] == 3
    assert body["pallet_breakdown"]["weight_pallets"] == 2
    assert body["base_price_usd"] is None


def test_fsa_single_zone_matches_even_when_city_name_differs() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "L4K 2N2", "preferred_city": "Vaughan", "province": "ON"},
        ],
        zone_rules=[
            {
                "postal_prefix": "L4K",
                "city": "VAUGHAN",
                "canonical_city": "VAUGHAN",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "match_level": "reference",
                "note": "",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(postal_code="L4K 2N2", city="Concord", province="ON", requires_appointment=False),
    )

    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "fsa_single_zone"
    assert body["origin"] == "toronto"
    assert body["zone"] == 2
    assert body["manual_review_required"] is False


def test_city_alias_resolves_multi_zone_fsa() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "L4K 2N2", "preferred_city": "Concord", "province": "ON"},
        ],
        city_aliases=[
            {
                "province": "ON",
                "alias_city": "CONCORD",
                "canonical_city": "VAUGHAN",
                "alias_type": "suburb",
            },
        ],
        zone_rules=[
            {
                "postal_prefix": "L4K",
                "city": "VAUGHAN",
                "canonical_city": "VAUGHAN",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "match_level": "reference",
                "note": "",
            },
            {
                "postal_prefix": "L4K",
                "city": "NORTH YORK",
                "canonical_city": "NORTH YORK",
                "province": "ON",
                "origin": "toronto",
                "zone": 4,
                "match_level": "reference",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "toronto",
                "zone": 2,
                "billing_pallets": 3,
                "base_price_usd": Decimal("120.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post("/quotes/zone-calculate", json=base_payload(requires_appointment=False))

    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "city_alias"
    assert body["match_trace"]["canonical_city_candidates"][0] == "VAUGHAN"
    assert body["zone"] == 2
    assert body["manual_review_required"] is False


def test_postal_zone_override_has_highest_priority() -> None:
    client = build_client(
        postal_overrides=[
            {
                "postal_code": "L4K 2N2",
                "postal_prefix": "L4K",
                "province": "ON",
                "canonical_city": "VAUGHAN",
                "origin": "toronto",
                "zone": 4,
                "confidence": 100,
                "source": "test_override",
            },
        ],
        prices=[
            {
                "origin": "toronto",
                "zone": 4,
                "billing_pallets": 3,
                "base_price_usd": Decimal("155.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post("/quotes/zone-calculate", json=base_payload(requires_appointment=False))

    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "postal_code_override"
    assert body["confidence"] == 100
    assert body["zone"] == 4
    assert body["base_price_usd"] == "155.00"


def test_inactive_zone_rules_are_ignored() -> None:
    client = build_client(
        zone_rules=[
            {
                "postal_prefix": "L4K",
                "city": "CONCORD",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "active": False,
                "match_level": "reference",
                "note": "",
            },
        ],
    )

    response = client.post("/quotes/zone-calculate", json=base_payload(requires_appointment=False))

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "city_fallback_not_found"
    assert body["manual_review_required"] is True


def test_city_zone_fallback_when_postal_prefix_missing() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "L1X 0P1", "preferred_city": "Pickering", "province": "ON"},
        ],
        zone_rules=[
            {
                "postal_prefix": "L1V",
                "city": "PICKERING",
                "province": "ON",
                "origin": "toronto",
                "zone": 3,
                "match_level": "reference",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "toronto",
                "zone": 3,
                "billing_pallets": 6,
                "base_price_usd": Decimal("250.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="1055 Flagship Way, unit A",
            postal_code="L1X 0P2",
            city="Pickering",
            province="ON",
            cbm=11.7,
            weight_kg=1367,
            piece_count=99,
            packaging_type="carton",
            longest_side_cm=None,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["origin"] == "toronto"
    assert body["zone"] == 3
    assert body["billing_pallets"] == 6
    assert body["base_price_usd"] == "250.00"
    assert "city_zone_fallback" in body["risk_tags"]
    assert body["manual_review_required"] is False


def test_city_zone_fallback_prefers_requested_postal_prefix_family() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V6Y 0C8", "preferred_city": "Richmond", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "B5A",
                "city": "RICHMOND",
                "province": "BC",
                "origin": "toronto",
                "zone": 10,
                "match_level": "reference",
                "note": "noisy Richmond record from a different postal family",
            },
            {
                "postal_prefix": "V6W",
                "city": "RICHMOND",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "match_level": "reference",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 2,
                "base_price_usd": Decimal("365.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="9699 Sills Ave #8",
            postal_code="V6Y 0C8",
            city=None,
            province=None,
            cbm=2.18,
            weight_kg=352.5,
            piece_count=15,
            packaging_type="carton",
            longest_side_cm=62.5,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["preferred_city"] == "Richmond"
    assert body["city"] == "Richmond"
    assert body["province"] == "BC"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 2
    assert body["base_price_usd"] == "365.00"
    assert body["fuel_usd"] == "127.75"
    assert body["total_price_usd"] == "492.75"
    assert "city_zone_fallback" in body["risk_tags"]
    assert "city_zone_prefix_family_fallback" in body["risk_tags"]
    assert "expected_origin_preferred" in body["risk_tags"]
    assert body["manual_review_required"] is False


def test_surrey_v3w_uses_expected_origin_adjacent_city_anchor() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V3W 3A4", "preferred_city": "Surrey", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V3R",
                "city": "SURREY",
                "province": "BC",
                "origin": "toronto",
                "zone": 10,
                "match_level": "legacy_anchor",
                "note": "stale Surrey origin from legacy table",
            },
            {
                "postal_prefix": "V4N",
                "city": "SURREY",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "match_level": "reference",
                "note": "Surrey BC Calgary anchor",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 3,
                "base_price_usd": Decimal("300.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="12529 80 Avenue",
            postal_code="V3W 3A4",
            city="Surrey",
            province="BC",
            cbm=3.753486,
            weight_kg=1063,
            piece_count=71,
            packaging_type="carton",
            longest_side_cm=44.5,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "city_zone_fallback"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 3
    assert body["base_price_usd"] == "300.00"
    assert body["fuel_usd"] == "105.00"
    assert body["total_price_usd"] == "405.00"
    assert "city_zone_prefix_family_fallback" in body["risk_tags"]
    assert "expected_origin_preferred" in body["risk_tags"]
    assert body["manual_review_required"] is False


def test_vancouver_v5l_uses_corrected_calgary_city_anchor() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V5L 3K9", "preferred_city": "Vancouver", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V5K",
                "city": "VANCOUVER",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "match_level": "L2",
                "note": "BC unified Calgary anchor",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 4,
                "base_price_usd": Decimal("560.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="1345 Clark Drive",
            postal_code="V5L 3K9",
            city="Vancouver",
            province="BC",
            cbm=7,
            weight_kg=2,
            piece_count=1,
            packaging_type="carton",
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "city_zone_fallback"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 4
    assert body["base_price_usd"] == "560.00"
    assert body["manual_review_required"] is False


def test_city_zone_fallback_allows_single_expected_origin_adjacent_anchor() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V5J 5M8", "preferred_city": "Burnaby", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V3J",
                "city": "BURNABY",
                "province": "BC",
                "origin": "toronto",
                "zone": 10,
                "match_level": "legacy_anchor",
                "note": "conflicting legacy Burnaby anchor",
            },
            {
                "postal_prefix": "V5H",
                "city": "BURNABY",
                "province": "BC",
                "origin": "calgary",
                "zone": 5,
                "match_level": "reference",
                "note": "",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 1,
                "base_price_usd": Decimal("240.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="8125 N Fraser Wy, Amaya dairy",
            postal_code="V5J 5M8",
            city="Burnaby",
            province="BC",
            cbm=0.88,
            weight_kg=80,
            piece_count=1,
            packaging_type="unknown",
            longest_side_cm=110,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "city_zone_fallback"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 1
    assert body["base_price_usd"] == "240.00"
    assert body["fuel_usd"] == "84.00"
    assert body["total_price_usd"] == "324.00"
    assert "city_zone_prefix_family_fallback" in body["risk_tags"]
    assert "expected_origin_preferred" in body["risk_tags"]


def test_ab_city_fallback_prefers_expected_origin_anchor_over_stale_toronto() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "T4B 2Z8", "preferred_city": "Rocky View County", "province": "AB"},
        ],
        zone_rules=[
            {
                "postal_prefix": "T1X",
                "city": "ROCKY VIEW COUNTY",
                "province": "AB",
                "origin": "toronto",
                "zone": 11,
                "match_level": "reference",
                "note": "stale origin from legacy table",
            },
            {
                "postal_prefix": "T1Z",
                "city": "ROCKY VIEW COUNTY",
                "province": "AB",
                "origin": "calgary",
                "zone": 11,
                "match_level": "trusted_city_anchor",
                "note": "trusted origin anchor",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 11,
                "billing_pallets": 6,
                "base_price_usd": Decimal("2000.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
        quote_rule_configs=[
            {
                "key": "zone_price_enabled_by_zone",
                "value": '{"calgary|11":true}',
                "description": None,
            }
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="263082 Range Road 13",
            postal_code="T4B 2Z8",
            city=None,
            province=None,
            cbm=3.63,
            weight_kg=2913,
            piece_count=1,
            packaging_type="pallet",
            longest_side_cm=150,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["origin"] == "calgary"
    assert body["zone"] == 11
    assert body["billing_pallets"] == 6
    assert body["base_price_usd"] == "2000.00"
    assert body["fuel_usd"] == "700.00"
    assert body["total_price_usd"] == "2700.00"
    assert "city_zone_fallback" in body["risk_tags"]
    assert body["manual_review_required"] is False


def test_regina_s4s_uses_corrected_calgary_zone_5() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "S4S 0A2", "preferred_city": "Regina", "province": "SK"},
        ],
        zone_rules=[
            {
                "postal_prefix": "S4S",
                "city": "REGINA",
                "province": "SK",
                "origin": "calgary",
                "zone": 5,
                "priority": 10,
                "match_level": "manual_correction",
                "note": "Regina S4S correction",
            },
            {
                "postal_prefix": "S4M",
                "city": "REGINA",
                "province": "SK",
                "origin": "toronto",
                "zone": 14,
                "match_level": "legacy_anchor",
                "note": "must not be used for S4S",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 15,
                "base_price_usd": Decimal("1450.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
            {
                "origin": "calgary",
                "zone": 14,
                "billing_pallets": 15,
                "base_price_usd": Decimal("6250.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="3737 Wascana Pkwy",
            postal_code="S4S 0A2",
            city="Regina",
            province="SK",
            cbm=22.43,
            weight_kg=7500,
            piece_count=2,
            packaging_type="wooden_crate",
            longest_side_cm=400,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "fsa_single_zone"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 15
    assert body["base_price_usd"] == "1450.00"
    assert body["fuel_usd"] == "507.50"
    assert body["total_price_usd"] == "1957.50"
    assert body["manual_review_required"] is False


def test_saskatoon_s7k_fuzzy_matches_calgary_zone_5_not_stale_toronto_zone_14() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "S7K 1X6", "preferred_city": "Saskatoon", "province": "SK"},
        ],
        zone_rules=[
            {
                "postal_prefix": "S7J",
                "city": "SASKATOON",
                "province": "SK",
                "origin": "calgary",
                "zone": 5,
                "match_level": "trusted_city_anchor",
                "note": "trusted Saskatoon S7 family anchor",
            },
            {
                "postal_prefix": "S7H",
                "city": "SASKATOON",
                "province": "SK",
                "origin": "toronto",
                "zone": 14,
                "match_level": "legacy_anchor",
                "note": "must not be used for S7K",
            },
        ],
            prices=[
                {
                    "origin": "calgary",
                    "zone": 5,
                    "billing_pallets": 3,
                    "base_price_usd": Decimal("180.00"),
                    "source": "test",
                    "last_updated": "2026-06-03",
                },
                {
                    "origin": "calgary",
                    "zone": 14,
                    "billing_pallets": 3,
                    "base_price_usd": Decimal("3550.00"),
                    "source": "test",
                    "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="480 1st Ave N",
            postal_code="S7K 1X6",
            city="Saskatoon",
            province="SK",
            cbm=3.84,
            weight_kg=1100,
            piece_count=3,
            packaging_type="carton",
            longest_side_cm=144,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "city_zone_fallback"
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 3
    assert body["pallet_breakdown"]["volume_pallets"] == 2
    assert body["pallet_breakdown"]["weight_pallets"] == 3
    assert body["pallet_breakdown"]["long_piece_pallets"] == 0
    assert body["base_price_usd"] == "180.00"
    assert body["fuel_usd"] == "63.00"
    assert body["total_price_usd"] == "243.00"
    assert "city_zone_fallback" in body["risk_tags"]
    assert "city_zone_prefix_family_fallback" in body["risk_tags"]
    assert body["match_trace"]["expected_origin"] == "calgary"
    assert body["match_trace"]["origin_preference_applied"] is True
    assert body["manual_review_required"] is False


def test_nanaimo_v9s_does_not_treat_fsa_character_distance_as_geography() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "V9S 5X9", "preferred_city": "Nanaimo", "province": "BC"},
        ],
        zone_rules=[
            {
                "postal_prefix": "V9P",
                "city": "PARKSVILLE",
                "province": "BC",
                "origin": "calgary",
                "zone": 7,
                "match_level": "reference",
                "note": "",
            },
            {
                "postal_prefix": "V9Y",
                "city": "PORT ALBERNI",
                "province": "BC",
                "origin": "calgary",
                "zone": 7,
                "match_level": "reference",
                "note": "",
            },
            {
                "postal_prefix": "V9Z",
                "city": "SOOKE",
                "province": "BC",
                "origin": "calgary",
                "zone": 12,
                "match_level": "reference",
                "note": "same family but farther from V9S",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 7,
                "billing_pallets": 6,
                "base_price_usd": Decimal("1050.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
            {
                "origin": "calgary",
                "zone": 12,
                "billing_pallets": 6,
                "base_price_usd": Decimal("2500.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="1975 Boxwood Rd #7",
            postal_code="V9S 5X9",
            city="Nanaimo",
            province="BC",
            cbm=10.76,
            weight_kg=1798,
            piece_count=200,
            packaging_type="carton",
            longest_side_cm=100,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "city_fallback_not_found"
    assert body["origin"] is None
    assert body["zone"] is None
    assert body["billing_pallets"] == 6
    assert body["base_price_usd"] is None
    assert body["fuel_usd"] is None
    assert body["total_price_usd"] is None
    assert "zone_not_found" in body["risk_tags"]
    assert body["manual_review_required"] is True


def test_port_colborne_l3k_does_not_borrow_woodbridge_l3l_zone() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "L3K 4B7", "preferred_city": "Port Colborne", "province": "ON"},
        ],
        zone_rules=[
            {
                "postal_prefix": "L3L",
                "city": "WOODBRIDGE",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "match_level": "reference",
                "note": "Alphabetically adjacent but geographically unrelated.",
            },
            {
                "postal_prefix": "L3B",
                "city": "WELLAND",
                "province": "ON",
                "origin": "toronto",
                "zone": 5,
                "match_level": "reference",
                "note": "Nearby city with a conflicting Zone.",
            },
        ],
        prices=[
            {
                "origin": "toronto",
                "zone": 2,
                "billing_pallets": 1,
                "base_price_usd": Decimal("90.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="484 Barrick Rd",
            postal_code="L3K 4B7",
            city="Port Colborne",
            province="ON",
            cbm=1,
            weight_kg=1,
            piece_count=1,
            packaging_type="carton",
            longest_side_cm=100,
            explicit_pallet_count=1,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "city_fallback_not_found"
    assert body["preferred_city"] == "Port Colborne"
    assert body["postal_prefix"] == "L3K"
    assert body["city"] == "Port Colborne"
    assert body["province"] == "ON"
    assert body["origin"] is None
    assert body["zone"] is None
    assert body["billing_pallets"] == 1
    assert body["base_price_usd"] is None
    assert body["total_price_usd"] is None
    assert body["manual_review_required"] is True


def test_edmonton_t6r_uses_calgary_zone9_correction() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "T6R 3E9", "preferred_city": "Edmonton", "province": "AB"},
        ],
        zone_rules=[
            {
                "postal_prefix": "T5A",
                "city": "EDMONTON",
                "province": "AB",
                "origin": "toronto",
                "zone": 9,
                "match_level": "legacy_anchor",
                "note": "stale origin should not be used",
            },
            {
                "postal_prefix": "T6R",
                "city": "EDMONTON",
                "province": "AB",
                "origin": "calgary",
                "zone": 9,
                "priority": 10,
                "match_level": "manual_correction",
                "note": "Edmonton T6R correction",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 9,
                "billing_pallets": 2,
                "base_price_usd": Decimal("630.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
            {
                "origin": "toronto",
                "zone": 9,
                "billing_pallets": 2,
                "base_price_usd": Decimal("460.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
        quote_rule_configs=[
            {
                "key": "zone_price_enabled_by_zone",
                "value": '{"calgary|9":true}',
                "description": None,
            }
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="440 Hodgson Blvd NW",
            postal_code="T6R 3E9",
            city="Edmonton",
            province="AB",
            cbm=2.5,
            weight_kg=224,
            piece_count=1,
            packaging_type="carton",
            longest_side_cm=216,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["matched_by"] == "fsa_single_zone"
    assert body["origin"] == "calgary"
    assert body["zone"] == 9
    assert body["billing_pallets"] == 2
    assert body["base_price_usd"] == "630.00"
    assert body["fuel_usd"] == "220.50"
    assert body["total_price_usd"] == "850.50"
    assert body["manual_review_required"] is False


def test_city_fallback_requires_expected_origin_anchor() -> None:
    client = build_client(
        postal_records=[
            {"postal_code": "S7K 1X6", "preferred_city": "Saskatoon", "province": "SK"},
        ],
        zone_rules=[
            {
                "postal_prefix": "S7H",
                "city": "SASKATOON",
                "province": "SK",
                "origin": "toronto",
                "zone": 14,
                "match_level": "legacy_anchor",
                "note": "wrong origin anchor should not drive postal family fallback",
            },
        ],
        prices=[
            {
                "origin": "calgary",
                "zone": 14,
                "billing_pallets": 6,
                "base_price_usd": Decimal("3550.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            address_line="480 1st Ave N",
            postal_code="S7K 1X6",
            city=None,
            province=None,
            cbm=3.84,
            weight_kg=1100,
            piece_count=3,
            packaging_type="carton",
            longest_side_cm=144,
            requires_appointment=False,
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "city_fallback_expected_origin_not_found"
    assert body["manual_review_required"] is True


def test_missing_matrix_price_does_not_estimate_by_multiplication() -> None:
    client = build_client(prices=[price for price in default_prices() if price["billing_pallets"] != 4])

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            cbm=1,
            weight_kg=100,
            piece_count=2,
            longest_side_cm=240,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["billing_pallets"] == 4
    assert body["pallet_breakdown"]["long_piece_pallets"] == 4
    assert body["total_price_usd"] is None
    assert "zone_price_not_found" in body["risk_tags"]
