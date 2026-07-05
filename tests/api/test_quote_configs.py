from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import APIKey, Base
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.api_keys import hash_api_key


ADMIN_KEY = "caq_admin_config_test_key"
SALES_KEY = "caq_sales_config_test_key"


def build_client() -> TestClient:
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
