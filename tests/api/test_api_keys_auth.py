from collections.abc import Generator
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import APIKey, Base, ManualQuoteTask, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.api_keys import API_KEY_PREFIX, hash_api_key


ADMIN_KEY = "caq_admin_test_key"
SALES_KEY = "caq_sales_test_key"
OPERATOR_KEY = "caq_operator_test_key"
VIEWER_KEY = "caq_viewer_test_key"
DISABLED_KEY = "caq_disabled_test_key"


def build_client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        for name, plain_key, role, enabled in [
            ("Admin", ADMIN_KEY, "admin", True),
            ("Sales", SALES_KEY, "sales", True),
            ("Operator", OPERATOR_KEY, "operator", True),
            ("Viewer", VIEWER_KEY, "viewer", True),
            ("Disabled", DISABLED_KEY, "admin", False),
        ]:
            session.add(APIKey(name=name, key_hash=hash_api_key(plain_key), role=role, enabled=enabled))

        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
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
        session.add(
            ManualQuoteTask(
                quote_id="quote_test_manual",
                reason="manual_required",
                risk_tags=["manual_required"],
                request_json={},
                result_json={},
                status="pending",
            )
        )
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def headers(api_key: str) -> dict[str, str]:
    return {"X-API-Key": api_key}


def quote_payload() -> dict[str, object]:
    return {
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


def test_missing_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.post("/quotes/zone-calculate", json=quote_payload())

    assert response.status_code == 401


def test_disabled_api_key_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.post("/quotes/zone-calculate", json=quote_payload(), headers=headers(DISABLED_KEY))

    assert response.status_code == 401


def test_admin_can_create_api_key_and_plaintext_is_returned_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.post(
        "/api-keys",
        json={"name": "Ops", "role": "operator"},
        headers=headers(ADMIN_KEY),
    )
    list_response = client.get("/api-keys", headers=headers(ADMIN_KEY))

    assert response.status_code == 201
    body = response.json()
    listed = list_response.json()
    assert body["api_key"].startswith(API_KEY_PREFIX)
    assert "key_hash" not in body
    assert body["masked_api_key"].startswith("caq_")
    assert all("api_key" not in item for item in listed)
    assert all("key_hash" not in item for item in listed)


def test_sales_can_create_quote_but_cannot_manage_ai_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    quote_response = client.post("/quotes/zone-calculate", json=quote_payload(), headers=headers(SALES_KEY))
    admin_response = client.get("/ai-configs", headers=headers(SALES_KEY))

    assert quote_response.status_code == 200
    assert quote_response.json()["source_type"] == "zone_matrix"
    assert admin_response.status_code == 403


def test_viewer_can_read_manual_tasks_but_cannot_update(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    read_response = client.get("/quotes/manual-tasks", headers=headers(VIEWER_KEY))
    patch_response = client.patch("/quotes/manual-tasks/1", json={"status": "resolved"}, headers=headers(VIEWER_KEY))

    assert read_response.status_code == 200
    assert patch_response.status_code == 403


def test_operator_can_update_manual_task(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/manual-tasks/1",
        json={"status": "resolved", "resolved_note": "Confirmed."},
        headers=headers(OPERATOR_KEY),
    )

    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
