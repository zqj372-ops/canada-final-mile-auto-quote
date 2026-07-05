from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base
from apps.api.db.session import get_db
from apps.api.main import app


def build_client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_create_ai_config_does_not_return_plain_api_key() -> None:
    client = build_client()

    response = client.post(
        "/ai-configs",
        json={
            "name": "Demo",
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-test-secret-abcd",
            "model_name": "gpt-test",
            "is_default": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "api_key" not in body
    assert "api_key_encrypted" not in body
    assert body["masked_api_key"] == "sk-****abcd"
    assert "sk-test-secret-abcd" not in response.text


def test_set_default_ai_config_clears_previous_default() -> None:
    client = build_client()
    first = client.post(
        "/ai-configs",
        json={
            "name": "First",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-first-0001",
            "model_name": "gpt-test",
            "is_default": True,
        },
    ).json()
    second = client.post(
        "/ai-configs",
        json={
            "name": "Second",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-second-0002",
            "model_name": "gpt-test",
        },
    ).json()

    response = client.post(f"/ai-configs/{second['id']}/set-default")

    assert response.status_code == 200
    configs = client.get("/ai-configs").json()
    defaults = [config for config in configs if config["is_default"]]
    assert len(defaults) == 1
    assert defaults[0]["id"] == second["id"]
    assert first["id"] != defaults[0]["id"]


def test_ai_config_test_failure_returns_structured_error() -> None:
    client = build_client()
    config = client.post(
        "/ai-configs",
        json={
            "name": "Broken",
            "base_url": "http://127.0.0.1:9/v1",
            "api_key": "sk-broken-0000",
            "model_name": "gpt-test",
            "timeout_seconds": 1,
        },
    ).json()

    response = client.post(f"/ai-configs/{config['id']}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is False
    assert body["error"]
    assert isinstance(body["latency_ms"], int)
