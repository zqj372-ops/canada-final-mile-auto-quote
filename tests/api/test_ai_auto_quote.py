from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import AIModelConfig, Base, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft
from packages.quote_engine.zone_models import ZoneQuoteResult


def build_client(*, include_zone_rule: bool = True, include_default_config: bool = True) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        if include_default_config:
            session.add(
                AIModelConfig(
                    name="Default AI",
                    provider="openai",
                    base_url="https://example.invalid/v1",
                    api_key_encrypted="xor1:AA==",
                    model_name="gpt-test",
                    temperature=0,
                    max_tokens=800,
                    timeout_seconds=1,
                    is_default=True,
                    enabled=True,
                    purpose="general",
                )
            )
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
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def complete_extraction() -> AIExtractedQuoteDraft:
    return AIExtractedQuoteDraft(
        address_line="8888 Keele St",
        postal_code="L4K 2N2",
        city="Concord",
        province="ON",
        cbm=Decimal("4.2"),
        weight_kg=Decimal("850"),
        piece_count=10,
        packaging_type="carton",
        longest_side_cm=Decimal("100"),
        address_type="commercial",
        requires_appointment=True,
        missing_fields=[],
        confidence=95,
    )


def test_ai_auto_quote_without_default_config_returns_clear_error() -> None:
    client = build_client(include_default_config=False)

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 400
    assert response.json()["detail"] == "No default AI model config is available."


def test_ai_extraction_missing_fields_does_not_call_zone_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()

    def fake_extract(_message: str, _client: object) -> AIExtractedQuoteDraft:
        return AIExtractedQuoteDraft(
            postal_code="L4K 2N2",
            missing_fields=["cbm", "weight_kg", "piece_count", "packaging_type", "address_type"],
            confidence=55,
        )

    def fail_quote(*_args: object, **_kwargs: object) -> ZoneQuoteResult:
        raise AssertionError("Zone Quote Engine should not be called when required fields are missing.")

    monkeypatch.setattr("apps.api.routes.quotes.extract_quote_draft", fake_extract)
    monkeypatch.setattr("apps.api.routes.quotes.ZoneQuoteEngine.quote", fail_quote)

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"] is None
    assert "cbm" in body["missing_fields"]
    assert "Zone Quote Engine was not called" in body["internal_note"]


def test_ai_extraction_complete_calls_zone_quote_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()
    monkeypatch.setattr("apps.api.routes.quotes.extract_quote_draft", lambda _message, _client: complete_extraction())
    monkeypatch.setattr(
        "apps.api.routes.quotes._build_guarded_sales_note",
        lambda _client, quote_result: quote_result.sales_note,
    )

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"]["source_type"] == "zone_matrix"
    assert body["quote_result"]["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False


def test_ai_auto_quote_manual_required_creates_manual_task(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(include_zone_rule=False)
    monkeypatch.setattr("apps.api.routes.quotes.extract_quote_draft", lambda _message, _client: complete_extraction())

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})
    tasks = client.get("/quotes/manual-tasks").json()

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"]["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert len(tasks) == 1
    assert tasks[0]["quote_id"] == body["quote_result"]["quote_id"]
