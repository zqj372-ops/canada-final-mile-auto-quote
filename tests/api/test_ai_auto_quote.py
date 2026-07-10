from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import AIModelConfig, Base, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.services.ai_quote_service import _build_guarded_sales_note
from apps.api.main import app
from packages.ai_assistant.model_client import AIResponse
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, QuoteExtractionError
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


class FakeSalesNoteClient:
    def __init__(self, content: str):
        self.content = content

    def complete(self, _messages: object) -> AIResponse:
        return AIResponse(content=self.content)


def priced_quote_result(*, sales_note: str = "加拿大尾端派送报价：\n报价：USD 212.00") -> ZoneQuoteResult:
    return ZoneQuoteResult(
        source_type="zone_matrix",
        confidence=90,
        postal_code="L4K 2N2",
        postal_prefix="L4K",
        city="Concord",
        province="ON",
        origin="toronto",
        zone=2,
        billing_pallets=3,
        base_price_usd=Decimal("120.00"),
        fuel_usd=Decimal("42.00"),
        accessorials={"appointment_fee_usd": Decimal("50.00")},
        total_price_usd=Decimal("212.00"),
        manual_review_required=False,
        matched_rule="zone_matrix + toronto + ON + Concord + L4K + Zone 2 + 3 pallets",
        sales_note=sales_note,
    )


def test_ai_sales_note_blocks_internal_reasoning_and_uses_short_fallback() -> None:
    verbose_internal_note = """
<think>这里是模型思考过程</think>
## 报价说明
报价编号：abc
| 费用项 | 金额 |
| 基础派送费 | $120.00 USD |
总价：$212.00 USD，价格已锁定。
"""

    result = _build_guarded_sales_note(
        FakeSalesNoteClient(verbose_internal_note),
        priced_quote_result(sales_note="加拿大尾端派送报价：\n报价：USD 212.00"),
    )

    assert result == "加拿大尾端派送报价：\n报价：USD 212.00"
    assert "<think>" not in result
    assert "报价编号" not in result
    assert "|" not in result


def test_ai_sales_note_keeps_concise_customer_message() -> None:
    concise_note = (
        "加拿大尾端派送报价：\n"
        "目的地：Concord ON L4K 2N2\n"
        "货物：4.2 CBM / 850 KG / 10件\n"
        "报价：USD 212.00\n"
        "备注：请确认是否有 dock/叉车。"
    )

    result = _build_guarded_sales_note(FakeSalesNoteClient(concise_note), priced_quote_result())

    assert result == concise_note


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

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", fake_extract)
    monkeypatch.setattr("apps.api.services.ai_quote_service.ZoneQuoteEngine.quote", fail_quote)

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"] is None
    assert "cbm" in body["missing_fields"]
    assert "Zone Quote Engine was not called" in body["internal_note"]


def test_ai_missing_fields_creates_manual_task(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()

    def fake_extract(_message: str, _client: object) -> AIExtractedQuoteDraft:
        return AIExtractedQuoteDraft(
            postal_code="L4K 2N2",
            missing_fields=["cbm", "weight_kg", "address_type"],
            confidence=55,
        )

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", fake_extract)

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})
    tasks = client.get("/quotes/manual-tasks").json()

    assert response.status_code == 200
    assert len(tasks) == 1
    assert tasks[0]["quote_id"].isdigit()
    assert len(tasks[0]["quote_id"]) == 31
    assert "ai_missing_fields" in tasks[0]["risk_tags"]
    assert "cbm" in tasks[0]["result_json"]["missing_fields"]


def test_ai_provider_failure_returns_manual_review_instead_of_502(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()

    def fake_extract(_message: str, _client: object) -> AIExtractedQuoteDraft:
        raise QuoteExtractionError("provider returned 502")

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", fake_extract)

    response = client.post(
        "/quotes/ai-auto-quote",
        json={"customer_message": "170*140*87 409kg\nT0B 3L0 Alberta"},
    )
    tasks = client.get("/quotes/manual-tasks").json()

    assert response.status_code == 200
    body = response.json()
    assert body["manual_review_required"] is True
    assert body["quote_result"] is None
    assert body["internal_note"] == "AI field extraction failed. Manual review task was created; no price was generated."
    assert len(tasks) == 1
    assert tasks[0]["quote_id"].isdigit()
    assert len(tasks[0]["quote_id"]) == 31
    assert "ai_extraction_failed" in tasks[0]["risk_tags"]


def test_ai_provider_failure_uses_complete_deterministic_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()

    def fake_extract(_message: str, _client: object) -> AIExtractedQuoteDraft:
        raise QuoteExtractionError("provider returned 502")

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", fake_extract)
    monkeypatch.setattr(
        "apps.api.services.ai_quote_service._build_guarded_sales_note",
        lambda _client, quote_result: quote_result.sales_note,
    )

    response = client.post(
        "/quotes/ai-auto-quote",
        json={
            "customer_message": (
                "加拿大地址：8888 Keele St, Concord ON, L4K 2N2\n"
                "常规纸箱尺寸 10箱 4.2cbm 850kg\n"
                "packaging_type=carton\n"
                "address_type=commercial\n"
                "requires_appointment=true\n"
            )
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["missing_fields"] == []
    assert body["manual_review_required"] is False
    assert body["extraction"]["city"] == "Concord"
    assert body["extraction"]["address_type"] == "commercial"
    assert body["quote_result"]["source_type"] == "zone_matrix"
    assert body["quote_result"]["billing_pallets"] == 3
    assert body["quote_result"]["total_price_usd"] == "212.00"
    assert body["address_validation"]["status"] == "verified"
    assert body["address_validation"]["preferred_city"] == "Concord"
    assert body["address_validation"]["province"] == "ON"
    assert "deterministic parser generated" in body["internal_note"]


def test_ai_extraction_complete_calls_zone_quote_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()
    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", lambda _message, _client: complete_extraction())
    monkeypatch.setattr(
        "apps.api.services.ai_quote_service._build_guarded_sales_note",
        lambda _client, quote_result: quote_result.sales_note,
    )

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"]["source_type"] == "zone_matrix"
    assert body["quote_result"]["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False
    assert body["address_validation"]["matched"] is True
    assert body["address_validation"]["postal_code"] == "L4K 2N2"


def test_ai_optional_missing_fields_still_calls_zone_quote_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()

    def aggregate_extraction() -> AIExtractedQuoteDraft:
        return AIExtractedQuoteDraft(
            address_line="1055 Flagship Way, unit A",
            postal_code="L1X 0P2",
            city="Pickering",
            province="ON",
            cbm=Decimal("11.7"),
            weight_kg=Decimal("1367"),
            piece_count=99,
            packaging_type="carton",
            longest_side_cm=None,
            explicit_pallet_count=None,
            is_stackable=None,
            address_type="commercial",
            missing_fields=["longest_side_cm", "explicit_pallet_count", "is_stackable"],
            confidence=86,
        )

    def fake_quote(*_args: object, **_kwargs: object) -> ZoneQuoteResult:
        return ZoneQuoteResult(
            source_type="zone_matrix",
            confidence=85,
            postal_code="L1X 0P2",
            postal_prefix="L1X",
            city="Pickering",
            province="ON",
            origin="toronto",
            zone=2,
            billing_pallets=6,
            base_price_usd=Decimal("120.00"),
            fuel_usd=Decimal("42.00"),
            total_price_usd=Decimal("162.00"),
            manual_review_required=False,
            matched_rule="test",
            sales_note="locked",
        )

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", lambda _message, _client: aggregate_extraction())
    monkeypatch.setattr("apps.api.services.ai_quote_service.ZoneQuoteEngine.quote", fake_quote)
    monkeypatch.setattr(
        "apps.api.services.ai_quote_service._build_guarded_sales_note",
        lambda _client, quote_result: quote_result.sales_note,
    )

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    body = response.json()
    assert body["missing_fields"] == []
    assert body["quote_result"]["source_type"] == "zone_matrix"
    assert body["manual_review_required"] is False


def test_ai_aggregate_manual_required_still_returns_billing_pallet_estimate(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()

    monkeypatch.setattr(
        "apps.api.services.ai_quote_service.extract_quote_draft",
        lambda _message, _client: AIExtractedQuoteDraft(
            address_line="1055 Flagship Way, unit A",
            postal_code="L1X 0P2",
            city="Pickering",
            province="ON",
            cbm=Decimal("11.7"),
            weight_kg=Decimal("1367"),
            piece_count=99,
            packaging_type="carton",
            longest_side_cm=None,
            explicit_pallet_count=None,
            is_stackable=None,
            address_type="commercial",
            missing_fields=["longest_side_cm", "explicit_pallet_count", "is_stackable"],
            confidence=86,
        ),
    )

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    body = response.json()
    assert body["missing_fields"] == []
    assert body["quote_result"]["source_type"] == "manual_required"
    assert body["quote_result"]["billing_pallets"] == 6
    assert body["quote_result"]["pallet_breakdown"]["volume_pallets"] == 6
    assert body["quote_result"]["pallet_breakdown"]["weight_pallets"] == 3
    assert body["quote_result"]["total_price_usd"] is None


def test_ai_auto_quote_manual_required_creates_manual_task(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(include_zone_rule=False)
    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", lambda _message, _client: complete_extraction())

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})
    tasks = client.get("/quotes/manual-tasks").json()

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"]["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert len(tasks) == 1
    assert tasks[0]["quote_id"] == body["quote_result"]["quote_id"]
