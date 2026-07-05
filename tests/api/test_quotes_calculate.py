from decimal import Decimal
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, VendorRateRule
from apps.api.db.session import get_db
from apps.api.main import app
from packages.quote_engine.models import SourceType


def build_client(records: list[dict[str, object]]) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        for record in records:
            session.add(VendorRateRule(**record))
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def rule(**overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "rule_id": "rule-1",
        "source_type": SourceType.FSA.value,
        "origin_warehouse": "Toronto",
        "vendor_name": "Demo Carrier",
        "province": "ON",
        "city": "Concord",
        "fsa": "L4K",
        "postal_code": None,
        "pallet_min": 1,
        "pallet_max": 3,
        "weight_min_kg": None,
        "weight_max_kg": Decimal("1500.00"),
        "base_cost_cad": Decimal("100.00"),
        "fuel_percent": Decimal("10.00"),
        "appointment_fee_cad": Decimal("15.00"),
        "liftgate_fee_cad": Decimal("0.00"),
        "residential_fee_cad": Decimal("0.00"),
        "limited_access_fee_cad": Decimal("0.00"),
        "remote_fee_cad": Decimal("0.00"),
        "status": "active",
    }
    values.update(overrides)
    return values


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_quotes_calculate_matches_fsa_rule() -> None:
    client = build_client([rule()])

    response = client.post(
        "/quotes/calculate",
        json={
            "address_line": "8888 Keele St",
            "postal_code": "L4K 2N2",
            "city": "Concord",
            "province": "ON",
            "origin_warehouse": "Toronto",
            "pallet_count": 3,
            "weight_kg": 850,
            "requires_appointment": True,
            "requires_liftgate": False,
            "is_residential": False,
            "dock_available": None,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == SourceType.FSA.value
    assert body["confidence"] == 80
    assert body["manual_review_required"] is False
    assert body["matched_rule"] == "fsa + Toronto + ON + Concord + L4K + 3 pallets"


def test_quotes_calculate_postal_code_priority_beats_fsa() -> None:
    client = build_client(
        [
            rule(rule_id="fsa-rule", base_cost_cad=Decimal("100.00")),
            rule(
                rule_id="postal-rule",
                source_type=SourceType.POSTAL_CODE.value,
                postal_code="L4K 2N2",
                base_cost_cad=Decimal("120.00"),
            ),
        ]
    )

    response = client.post(
        "/quotes/calculate",
        json={
            "postal_code": "L4K 2N2",
            "city": "Concord",
            "province": "ON",
            "origin_warehouse": "Toronto",
            "pallet_count": 3,
            "weight_kg": 850,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == SourceType.POSTAL_CODE.value
    assert body["matched_rule"] == "postal_code + Toronto + ON + Concord + L4K 2N2 + 3 pallets"


def test_quotes_calculate_returns_manual_required_when_no_candidate_matches() -> None:
    client = build_client([rule(fsa="L5T", city="Mississauga")])

    response = client.post(
        "/quotes/calculate",
        json={
            "postal_code": "L4K 2N2",
            "city": "Concord",
            "province": "ON",
            "origin_warehouse": "Toronto",
            "pallet_count": 3,
            "weight_kg": 850,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == SourceType.MANUAL_REQUIRED.value
    assert body["confidence"] == 0
    assert body["internal_cost_cad"] is None
    assert body["suggested_selling_price_cad"] is None
    assert body["manual_review_required"] is True


def test_quotes_calculate_rejects_inline_rate_rules() -> None:
    client = build_client([])

    response = client.post(
        "/quotes/calculate",
        json={
            "postal_code": "L4K 2N2",
            "city": "Concord",
            "province": "ON",
            "origin_warehouse": "Toronto",
            "pallet_count": 3,
            "rate_rules": [],
        },
    )

    assert response.status_code == 422
