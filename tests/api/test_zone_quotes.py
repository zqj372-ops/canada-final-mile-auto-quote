from decimal import Decimal
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app


def build_client(
    *,
    postal_records: list[dict[str, object]] | None = None,
    zone_rules: list[dict[str, object]] | None = None,
    prices: list[dict[str, object]] | None = None,
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
        for record in zone_rules or default_zone_rules():
            session.add(ZoneLookupRule(**record))
        for record in prices or default_prices():
            session.add(ZonePriceMatrix(**record))
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
    assert body["confidence"] == 85
    assert body["origin"] == "toronto"
    assert body["zone"] == 2
    assert body["billing_pallets"] == 3
    assert body["base_price_usd"] == "120.00"
    assert body["fuel_usd"] == "42.00"
    assert body["accessorials"]["appointment_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False


def test_v6v_richmond_bc_origin_is_overridden_to_calgary() -> None:
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
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert "stale_origin_overridden" in body["risk_tags"]
    assert body["manual_review_required"] is False


def test_split_record_without_unique_confirmation_returns_manual_required() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(postal_code="T1X 0A0", city=None, province=None, requires_appointment=False),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert "split_record_conflict" in body["risk_tags"]


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


def test_long_piece_over_120cm_counts_two_pallets_per_piece() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            cbm=1,
            weight_kg=100,
            piece_count=2,
            longest_side_cm=121,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["billing_pallets"] == 4
    assert body["base_price_usd"] == "135.00"


def test_missing_zone_returns_manual_required() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(postal_code="L5T 2X3", city="Mississauga", province="ON"),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["base_price_usd"] is None


def test_missing_matrix_price_does_not_estimate_by_multiplication() -> None:
    client = build_client(prices=[price for price in default_prices() if price["billing_pallets"] != 4])

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            cbm=1,
            weight_kg=100,
            piece_count=2,
            longest_side_cm=121,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["total_price_usd"] is None
    assert "zone_price_not_found" in body["risk_tags"]

