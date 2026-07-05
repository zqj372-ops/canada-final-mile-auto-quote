from decimal import Decimal
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, PostalCodeCityLookup, QuoteRuleConfig, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app


def build_client(*, include_zone_rule: bool = True, config_rows: list[dict[str, object]] | None = None) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        if include_zone_rule:
            session.add(
                ZoneLookupRule(
                    postal_prefix="L4K",
                    city="CONCORD",
                    province="ON",
                    origin="toronto",
                    zone=2,
                    match_level="test",
                    note="",
                )
            )
        session.add(
            ZonePriceMatrix(
                origin="toronto",
                zone=2,
                billing_pallets=3,
                base_price_usd=Decimal("120.00"),
                source="test",
                last_updated="2026-06-03",
            )
        )
        for row in config_rows or []:
            session.add(QuoteRuleConfig(**row))
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def payload(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
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
    data.update(overrides)
    return data


def test_zone_calculate_success_writes_audit_log() -> None:
    client = build_client()

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    audit = client.get(f"/quotes/audit/{quote['quote_id']}")

    assert audit.status_code == 200
    body = audit.json()
    assert body["quote_id"] == quote["quote_id"]
    assert body["source_type"] == "zone_matrix"
    assert body["postal_prefix"] == "L4K"
    assert body["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False


def test_manual_required_writes_audit_log() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    audit = client.get(f"/quotes/audit/{quote['quote_id']}").json()

    assert quote["source_type"] == "manual_required"
    assert audit["quote_id"] == quote["quote_id"]
    assert audit["manual_review_required"] is True
    assert audit["total_price_usd"] is None


def test_manual_required_creates_manual_quote_task() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    tasks = client.get("/quotes/manual-tasks").json()

    assert len(tasks) == 1
    assert tasks[0]["quote_id"] == quote["quote_id"]
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["reason"] == quote["matched_rule"]


def test_successful_quote_does_not_create_manual_quote_task() -> None:
    client = build_client()

    client.post("/quotes/zone-calculate", json=payload())
    tasks = client.get("/quotes/manual-tasks").json()

    assert tasks == []


def test_manual_quote_task_can_be_patched() -> None:
    client = build_client(include_zone_rule=False)
    client.post("/quotes/zone-calculate", json=payload())
    task = client.get("/quotes/manual-tasks").json()[0]

    response = client.patch(
        f"/quotes/manual-tasks/{task['id']}",
        json={
            "status": "resolved",
            "assigned_to": "ops@example.com",
            "resolved_price_usd": "250.00",
            "resolved_note": "Confirmed with supplier.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["assigned_to"] == "ops@example.com"
    assert body["resolved_price_usd"] == "250.00"
    assert body["resolved_note"] == "Confirmed with supplier."


def test_zone_calculate_uses_database_pricing_config() -> None:
    client = build_client(
        config_rows=[
            {"key": "fuel_percent", "value": "10", "description": None},
            {"key": "appointment_fee_usd", "value": "20", "description": None},
        ]
    )

    quote = client.post("/quotes/zone-calculate", json=payload()).json()

    assert quote["fuel_usd"] == "12.00"
    assert quote["accessorials"]["appointment_fee_usd"] == "20.00"
    assert quote["total_price_usd"] == "152.00"

