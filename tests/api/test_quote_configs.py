from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import APIKey, Base, ZoneLookupRule
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.api_keys import hash_api_key


ADMIN_KEY = "caq_admin_config_test_key"
SALES_KEY = "caq_sales_config_test_key"


def build_client(zone_rules: list[dict[str, object]] | None = None) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        session.add(APIKey(name="Admin", key_hash=hash_api_key(ADMIN_KEY), role="admin", enabled=True))
        session.add(APIKey(name="Sales", key_hash=hash_api_key(SALES_KEY), role="sales", enabled=True))
        for rule in zone_rules or []:
            session.add(ZoneLookupRule(**rule))
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_get_workbench_config_returns_backend_defaults() -> None:
    client = build_client()

    response = client.get("/quote-configs/workbench")

    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "加拿大尾端 AI 报价系统"
    assert body["defaults"]["packaging_type"] == "unknown"
    assert body["parser"]["postal_code_pattern"]


def test_admin_can_update_workbench_config() -> None:
    client = build_client()
    current = client.get("/quote-configs/workbench").json()
    current["primary_button_label"] = "后台配置按钮"
    current["risks"]["dense_density_kg_per_cbm"] = 230

    response = client.put(
        "/quote-configs/workbench",
        json=current,
        headers={"X-API-Key": ADMIN_KEY},
    )
    read_back = client.get("/quote-configs/workbench").json()

    assert response.status_code == 200
    assert read_back["primary_button_label"] == "后台配置按钮"
    assert read_back["risks"]["dense_density_kg_per_cbm"] == 230


def test_sales_can_read_but_cannot_update_workbench_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()
    current = client.get("/quote-configs/workbench", headers={"X-API-Key": SALES_KEY}).json()

    read_response = client.get("/quote-configs/workbench", headers={"X-API-Key": SALES_KEY})
    update_response = client.put(
        "/quote-configs/workbench",
        json=current,
        headers={"X-API-Key": SALES_KEY},
    )

    assert read_response.status_code == 200
    assert update_response.status_code == 403


def test_admin_can_create_search_config_without_plain_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.post(
        "/search-configs",
        json={
            "name": "Tavily",
            "provider": "tavily",
            "base_url": "https://api.tavily.com",
            "api_key": "tvly-secret-1234",
            "is_default": True,
        },
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["masked_api_key"] == "tvl****1234"
    assert "api_key" not in body
    assert "api_key_encrypted" not in body
    assert "tvly-secret-1234" not in response.text


def test_sales_cannot_manage_search_configs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.get("/search-configs", headers={"X-API-Key": SALES_KEY})

    assert response.status_code == 403


def test_admin_can_manage_zone_pricing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    read_response = client.get("/quote-configs/zone-pricing", headers={"X-API-Key": ADMIN_KEY})
    update_response = client.put(
        "/quote-configs/zone-pricing",
        json={
            "fuel_percent": "18.5",
            "fuel_percent_by_zone": {"calgary|1": "12.5"},
            "zone_price_enabled": False,
            "max_auto_quote_zone": 6,
            "zone_price_enabled_by_zone": {"calgary|1": False, "calgary|8": True},
            "residential_fee_usd": "55",
            "liftgate_fee_usd": "60",
            "pallet_jack_fee_usd": "50",
            "appointment_fee_usd": "45",
            "detention_half_hour_fee_usd": "40",
            "detention_free_minutes": 20,
        },
        headers={"X-API-Key": ADMIN_KEY},
    )
    read_back = client.get("/quote-configs/zone-pricing", headers={"X-API-Key": ADMIN_KEY})

    assert read_response.status_code == 200
    assert read_response.json()["fuel_percent"] == "35"
    assert read_response.json()["fuel_percent_by_zone"] == {}
    assert read_response.json()["zone_price_enabled"] is True
    assert read_response.json()["max_auto_quote_zone"] == 7
    assert read_response.json()["zone_price_enabled_by_zone"] == {}
    assert update_response.status_code == 200
    assert read_back.json()["fuel_percent"] == "18.5"
    assert read_back.json()["fuel_percent_by_zone"] == {"calgary|1": "12.5"}
    assert read_back.json()["zone_price_enabled"] is False
    assert read_back.json()["max_auto_quote_zone"] == 6
    assert read_back.json()["zone_price_enabled_by_zone"] == {
        "calgary|1": False,
        "calgary|8": True,
    }
    assert read_back.json()["detention_free_minutes"] == 20


def test_admin_can_upsert_zone_price_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    first = client.post(
        "/quote-configs/zone-price-matrix",
        json={
            "origin": "Toronto",
            "zone": 3,
            "billing_pallets": 2,
            "base_price_usd": "250.00",
            "source": "unit-test",
            "last_updated": "2026-07-06",
        },
        headers={"X-API-Key": ADMIN_KEY},
    )
    second = client.post(
        "/quote-configs/zone-price-matrix",
        json={
            "origin": "toronto",
            "zone": 3,
            "billing_pallets": 2,
            "base_price_usd": "260.00",
            "source": "unit-test-updated",
        },
        headers={"X-API-Key": ADMIN_KEY},
    )
    listing = client.get(
        "/quote-configs/zone-price-matrix?origin=toronto&zone=3",
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert first.status_code == 200
    assert first.json()["origin"] == "toronto"
    assert second.status_code == 200
    assert second.json()["base_price_usd"] == "260.00"
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["records"][0]["source"] == "unit-test-updated"


def test_sales_cannot_manage_zone_price_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.get("/quote-configs/zone-price-matrix", headers={"X-API-Key": SALES_KEY})

    assert response.status_code == 403


def test_admin_can_list_create_update_and_deactivate_zone_city_rules(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client(
        zone_rules=[
            {
                "postal_prefix": "L5T",
                "city": "MISSISSAUGA",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "canonical_city": "MISSISSAUGA",
                "priority": 100,
                "active": True,
                "match_level": "source",
            },
            {
                "postal_prefix": "L6T",
                "city": "BRAMPTON",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "canonical_city": "BRAMPTON",
                "priority": 100,
                "active": True,
                "match_level": "source",
            },
        ]
    )

    listing = client.get(
        "/quote-configs/zone-city-rules?origin=toronto&zone=2",
        headers={"X-API-Key": ADMIN_KEY},
    )
    created = client.post(
        "/quote-configs/zone-city-rules",
        json={
            "postal_prefix": "L4W",
            "city": "Mississauga",
            "province": "Ontario",
            "origin": "Toronto",
            "zone": 3,
            "note": "后台调整",
        },
        headers={"X-API-Key": ADMIN_KEY},
    )
    updated = client.patch(
        f"/quote-configs/zone-city-rules/{created.json()['id']}",
        json={"zone": 4, "note": "迁移至 Zone 4"},
        headers={"X-API-Key": ADMIN_KEY},
    )
    deactivated = client.delete(
        f"/quote-configs/zone-city-rules/{created.json()['id']}",
        headers={"X-API-Key": ADMIN_KEY},
    )
    active_listing = client.get(
        "/quote-configs/zone-city-rules?origin=toronto&zone=4",
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert listing.status_code == 200
    assert listing.json()["total"] == 2
    assert listing.json()["city_count"] == 2
    assert listing.json()["postal_prefix_count"] == 2
    assert created.status_code == 201
    assert created.json()["postal_prefix"] == "L4W"
    assert created.json()["city"] == "MISSISSAUGA"
    assert created.json()["province"] == "ON"
    assert updated.status_code == 200
    assert updated.json()["zone"] == 4
    assert updated.json()["note"] == "迁移至 Zone 4"
    assert deactivated.status_code == 200
    assert deactivated.json()["active"] is False
    assert active_listing.json()["total"] == 0


def test_zone_city_rule_rejects_geographic_mismatch_and_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client(
        zone_rules=[
            {
                "postal_prefix": "L5T",
                "city": "MISSISSAUGA",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "canonical_city": "MISSISSAUGA",
                "priority": 100,
                "active": True,
            }
        ]
    )

    mismatch = client.post(
        "/quote-configs/zone-city-rules",
        json={
            "postal_prefix": "T2A",
            "city": "Calgary",
            "province": "ON",
            "origin": "toronto",
            "zone": 1,
        },
        headers={"X-API-Key": ADMIN_KEY},
    )
    duplicate = client.post(
        "/quote-configs/zone-city-rules",
        json={
            "postal_prefix": "l5t",
            "city": "mississauga",
            "province": "ON",
            "origin": "toronto",
            "zone": 5,
        },
        headers={"X-API-Key": ADMIN_KEY},
    )

    assert mismatch.status_code == 422
    assert "属于 AB" in mismatch.json()["detail"]
    assert duplicate.status_code == 422
    assert "已有有效分区配置" in duplicate.json()["detail"]


def test_sales_cannot_manage_zone_city_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.get(
        "/quote-configs/zone-city-rules",
        headers={"X-API-Key": SALES_KEY},
    )

    assert response.status_code == 403
