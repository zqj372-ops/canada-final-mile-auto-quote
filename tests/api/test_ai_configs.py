from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base
from apps.api.db.session import get_db
from apps.api.main import app
from packages.ai_assistant.model_discovery import DiscoveredModel, ModelDiscoveryResult


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


def test_provider_presets_include_openrouter_and_custom() -> None:
    client = build_client()

    response = client.get("/ai-configs/provider-presets")

    assert response.status_code == 200
    providers = {item["provider"] for item in response.json()}
    assert "openrouter" in providers
    assert "custom" in providers


def test_discover_models_returns_models_without_storing_key(monkeypatch) -> None:
    client = build_client()

    def fake_discover_models(**values):
        return ModelDiscoveryResult(
            provider=values["provider"],
            base_url=values["base_url"],
            latency_ms=12,
            models=[DiscoveredModel(id="demo-model", display_name="Demo Model")],
        )

    monkeypatch.setattr("apps.api.routes.ai_configs.discover_models", fake_discover_models)

    response = client.post(
        "/ai-configs/discover-models",
        json={
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-discovery-only",
        },
    )
    configs = client.get("/ai-configs").json()

    assert response.status_code == 200
    assert response.json()["models"][0]["id"] == "demo-model"
    assert configs == []
    assert "sk-discovery-only" not in response.text


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


def test_hermes_agent_can_switch_api_key_and_model_config() -> None:
    client = build_client()
    first = client.post(
        "/ai-configs",
        json={
            "name": "Hermes Primary",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-or-primary-0001",
            "model_name": "anthropic/claude-sonnet-test",
        },
    ).json()
    second = client.post(
        "/ai-configs",
        json={
            "name": "Hermes Backup",
            "provider": "deepseek",
            "base_url": "https://api.deepseek.com/v1",
            "api_key": "sk-deepseek-backup-0002",
            "model_name": "deepseek-chat-test",
        },
    ).json()

    initial = client.get("/ai-configs/agents/hermes")
    selected = client.put("/ai-configs/agents/hermes", json={"config_id": first["id"]})
    switched = client.put("/ai-configs/agents/hermes", json={"config_id": second["id"]})

    assert initial.status_code == 200
    assert initial.json()["config"] is None
    assert selected.status_code == 200
    assert selected.json()["config"]["model_name"] == "anthropic/claude-sonnet-test"
    assert switched.status_code == 200
    assert switched.json()["config"]["id"] == second["id"]
    assert switched.json()["config"]["masked_api_key"] == "sk-****0002"
    assert "sk-deepseek-backup-0002" not in switched.text


def test_hermes_agent_model_can_be_created_and_assigned_atomically() -> None:
    client = build_client()

    response = client.post(
        "/ai-configs/agents/hermes/configs",
        json={
            "name": "Hermes Atomic",
            "provider": "openrouter",
            "base_url": "https://openrouter.ai/api/v1",
            "api_key": "sk-atomic-hermes-0003",
            "model_name": "anthropic/test-model",
            "enabled": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["config"]["name"] == "Hermes Atomic"
    assert body["config"]["masked_api_key"] == "sk-****0003"
    current = client.get("/ai-configs/agents/hermes").json()
    assert current["config"]["id"] == body["config"]["id"]
    assert len(client.get("/ai-configs").json()) == 1


def test_hermes_agent_rejects_disabled_config_and_clears_deleted_assignment() -> None:
    client = build_client()
    disabled = client.post(
        "/ai-configs",
        json={
            "name": "Disabled Hermes",
            "api_key": "sk-disabled-0001",
            "model_name": "disabled-model",
            "enabled": False,
        },
    ).json()
    enabled = client.post(
        "/ai-configs",
        json={
            "name": "Enabled Hermes",
            "api_key": "sk-enabled-0002",
            "model_name": "enabled-model",
        },
    ).json()

    rejected = client.put("/ai-configs/agents/hermes", json={"config_id": disabled["id"]})
    assigned = client.put("/ai-configs/agents/hermes", json={"config_id": enabled["id"]})
    deleted = client.delete(f"/ai-configs/{enabled['id']}")
    current = client.get("/ai-configs/agents/hermes")

    assert rejected.status_code == 422
    assert assigned.status_code == 200
    assert deleted.status_code == 200
    assert current.status_code == 200
    assert current.json()["config"] is None


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
