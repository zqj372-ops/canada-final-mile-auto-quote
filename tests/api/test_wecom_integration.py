from collections.abc import Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import AIModelConfig, Base, PostalCodeCityLookup, WeComBotConfig, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.secrets import encrypt_secret
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, ExtractedCargoItem
from packages.wecom.bot_client import WeComBotClient, WeComSendResult


FAKE_WEBHOOK = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=testabcd"


def build_client(
    *,
    include_zone_rule: bool = True,
    bot_rows: list[dict[str, object]] | None = None,
    include_ai_config: bool = True,
) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        if include_ai_config:
            session.add(
                AIModelConfig(
                    name="Default AI",
                    provider="openai",
                    base_url="https://example.invalid/v1",
                    api_key_encrypted=encrypt_secret("sk-test-0000"),
                    model_name="gpt-test",
                    is_default=True,
                    enabled=True,
                    purpose="general",
                )
            )
        for row in bot_rows or []:
            session.add(
                WeComBotConfig(
                    name=str(row.get("name", "Ops bot")),
                    webhook_url_encrypted=encrypt_secret(str(row.get("webhook_url", FAKE_WEBHOOK))),
                    bot_type=str(row.get("bot_type", "group_webhook")),
                    purpose=str(row.get("purpose", "general")),
                    enabled=bool(row.get("enabled", True)),
                    is_default=bool(row.get("is_default", False)),
                    mention_all_on_manual_required=bool(row.get("mention_all_on_manual_required", False)),
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


def quote_payload(**overrides: object) -> dict[str, object]:
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
        "handling_units": [
            {
                "quantity": 3,
                "packaging_type": "carton",
                "length_cm": "120",
                "width_cm": "100",
                "height_cm": "116.6666667",
                "unit_weight_kg": "283.3333333",
                "contained_customer_pieces": 10,
            }
        ],
    }
    data.update(overrides)
    return data


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
        cargo_items=[
            ExtractedCargoItem(
                quantity=3,
                packaging_type="pallet",
                length_cm=Decimal("120"),
                width_cm=Decimal("100"),
                height_cm=Decimal("116.6666667"),
                weight_kg=Decimal("283.3333333"),
                cbm=Decimal("1.4"),
                contained_customer_pieces=10,
                total_weight_kg=Decimal("850"),
                total_cbm=Decimal("4.2"),
                source_span="3 standard handling units",
            )
        ],
    )


def _audit_result(client: TestClient, quote_id: str) -> dict[str, object]:
    response = client.get(f"/quotes/audit/{quote_id}")
    assert response.status_code == 200
    body = response.json()
    result = body.get("result_json")
    assert isinstance(result, dict)
    return result


def test_create_bot_config_does_not_return_plain_webhook_url() -> None:
    client = build_client()

    response = client.post(
        "/wecom/bots",
        json={
            "name": "Ops",
            "webhook_url": FAKE_WEBHOOK,
            "purpose": "quote_success",
            "is_default": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert "webhook_url" not in body
    assert "webhook_url_encrypted" not in body
    assert body["masked_webhook_url"].endswith("key=****abcd")
    assert FAKE_WEBHOOK not in response.text


def test_create_aibot_config_does_not_require_webhook_or_return_secret() -> None:
    client = build_client()
    secret = "aibot-secret-test-value"

    response = client.post(
        "/wecom/bots",
        json={
            "name": "智能机器人",
            "bot_type": "wecom_aibot_long_connection",
            "bot_id": "aibot-test-id-123456",
            "secret": secret,
            "purpose": "ai_quote",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["bot_type"] == "wecom_aibot_long_connection"
    assert body["masked_webhook_url"] is None
    assert body["masked_bot_id"] == "aibot-****123456"
    assert body["has_secret"] is True
    assert secret not in response.text
    assert "secret_encrypted" not in body


def test_create_aibot_config_requires_secret() -> None:
    client = build_client()

    response = client.post(
        "/wecom/bots",
        json={
            "name": "智能机器人",
            "bot_type": "wecom_aibot_long_connection",
            "bot_id": "aibot-test-id-123456",
            "purpose": "ai_quote",
        },
    )

    assert response.status_code == 422


def test_list_bots_returns_masked_webhook_url() -> None:
    client = build_client(bot_rows=[{"purpose": "general"}])

    response = client.get("/wecom/bots")

    assert response.status_code == 200
    body = response.json()
    assert body[0]["masked_webhook_url"].endswith("key=****abcd")
    assert FAKE_WEBHOOK not in response.text


def test_wecom_test_webhook_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(bot_rows=[{"purpose": "general"}])

    monkeypatch.setattr(
        "apps.api.routes.wecom_configs.WeComBotClient.test_webhook",
        lambda _self: WeComSendResult(success=True, latency_ms=12, status_code=200),
    )

    response = client.post("/wecom/bots/1/test")

    assert response.status_code == 200
    assert response.json() == {"success": True, "error": None, "latency_ms": 12, "status_code": 200}


def test_wecom_test_webhook_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(bot_rows=[{"purpose": "general"}])

    monkeypatch.setattr(
        "apps.api.routes.wecom_configs.WeComBotClient.test_webhook",
        lambda _self: WeComSendResult(success=False, error="boom", latency_ms=9, status_code=500),
    )

    response = client.post("/wecom/bots/1/test")

    assert response.status_code == 200
    assert response.json()["success"] is False
    assert response.json()["error"] == "boom"


def test_wecom_test_aibot_long_connection_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client()
    created = client.post(
        "/wecom/bots",
        json={
            "name": "智能机器人",
            "bot_type": "wecom_aibot_long_connection",
            "bot_id": "aibot-test-id-123456",
            "secret": "aibot-secret-test-value",
            "purpose": "ai_quote",
        },
    )
    assert created.status_code == 201

    monkeypatch.setattr(
        "apps.api.routes.wecom_configs.WeComAIBotLongConnectionClient.test_connection",
        lambda _self: WeComSendResult(success=True, latency_ms=25, status_code=None),
    )

    response = client.post("/wecom/bots/1/test")

    assert response.status_code == 200
    assert response.json() == {"success": True, "error": None, "latency_ms": 25, "status_code": None}


def test_wecom_client_exception_does_not_return_webhook_url(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenClient:
        def __init__(self, *_args: object, **_kwargs: object):
            pass

        def __enter__(self) -> "BrokenClient":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def post(self, url: str, *, json: dict[str, object]) -> object:
            raise RuntimeError(f"boom {url} {json}")

    monkeypatch.setattr("packages.wecom.bot_client.httpx.Client", BrokenClient)

    result = WeComBotClient(FAKE_WEBHOOK).send_markdown("test")

    assert result.success is False
    assert result.error == "RuntimeError"
    assert FAKE_WEBHOOK not in result.model_dump_json()


def test_disabled_bot_does_not_send(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(bot_rows=[{"enabled": False, "purpose": "quote_success"}])

    def fail_send(*_args: object, **_kwargs: object) -> WeComSendResult:
        raise AssertionError("Disabled bot should not send.")

    monkeypatch.setattr("apps.api.services.notification_service.WeComBotClient.send_markdown", fail_send)

    response = client.post(
        "/quotes/zone-calculate",
        json={"quote": quote_payload(), "notify_wecom": True, "wecom_bot_id": 1},
    )

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is False
    assert public["billing_pallets"] == 3
    assert _audit_result(client, public["quote_id"])["source_type"] == "zone_matrix"


def test_zone_calculate_success_notify_sends_quote_success(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(bot_rows=[{"purpose": "quote_success"}])
    sent: list[str] = []

    def fake_send(_self: object, content: str) -> WeComSendResult:
        sent.append(content)
        return WeComSendResult(success=True, latency_ms=1, status_code=200)

    monkeypatch.setattr("apps.api.services.notification_service.WeComBotClient.send_markdown", fake_send)

    response = client.post("/quotes/zone-calculate", json={"quote": quote_payload(), "notify_wecom": True})

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is False
    assert public["billing_pallets"] == 3
    assert _audit_result(client, public["quote_id"])["source_type"] == "zone_matrix"
    assert len(sent) == 1
    assert "加拿大尾程报价成功" in sent[0]


def test_zone_calculate_manual_required_auto_sends_with_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(
        include_zone_rule=False,
        bot_rows=[{"purpose": "manual_required", "mention_all_on_manual_required": True}],
    )
    markdowns: list[str] = []
    mentions: list[list[str] | None] = []
    text_messages: list[str] = []

    def fake_send_markdown(_self: object, content: str) -> WeComSendResult:
        markdowns.append(content)
        return WeComSendResult(success=True, latency_ms=1, status_code=200)

    def fake_send_text(_self: object, _content: str, *, mentioned_list: list[str] | None = None, **_kwargs: object) -> WeComSendResult:
        text_messages.append(_content)
        mentions.append(mentioned_list)
        return WeComSendResult(success=True, latency_ms=1, status_code=200)

    monkeypatch.setattr("apps.api.services.notification_service.WeComBotClient.send_markdown", fake_send_markdown)
    monkeypatch.setattr("apps.api.services.notification_service.WeComBotClient.send_text", fake_send_text)

    response = client.post("/quotes/zone-calculate", json=quote_payload())

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is True
    assert public["billing_pallets"] is None
    assert _audit_result(client, public["quote_id"])["source_type"] == "manual_required"
    assert len(markdowns) == 1
    assert "需人工确认" in markdowns[0]
    assert text_messages == ["@all 有新的加拿大尾程报价需人工确认，请查看上一条详情。"]
    assert mentions == [["@all"]]


def test_manual_required_markdown_failure_still_sends_at_all_and_returns_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(
        include_zone_rule=False,
        bot_rows=[{"purpose": "manual_required", "mention_all_on_manual_required": True}],
    )
    mentions: list[list[str] | None] = []

    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_markdown",
        lambda _self, _content: WeComSendResult(success=False, error="failed", latency_ms=1, status_code=500),
    )
    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_text",
        lambda _self, _content, *, mentioned_list=None, **_kwargs: mentions.append(mentioned_list)
        or WeComSendResult(success=True, latency_ms=1, status_code=200),
    )

    response = client.post("/quotes/zone-calculate", json=quote_payload())

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is True
    assert public["billing_pallets"] is None
    assert _audit_result(client, public["quote_id"])["source_type"] == "manual_required"
    assert mentions == [["@all"]]


def test_manual_required_at_all_exception_does_not_affect_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(
        include_zone_rule=False,
        bot_rows=[{"purpose": "manual_required", "mention_all_on_manual_required": True}],
    )

    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_markdown",
        lambda _self, _content: WeComSendResult(success=True, latency_ms=1, status_code=200),
    )

    def raise_text_error(*_args: object, **_kwargs: object) -> WeComSendResult:
        raise RuntimeError("text send failed")

    monkeypatch.setattr("apps.api.services.notification_service.WeComBotClient.send_text", raise_text_error)

    response = client.post("/quotes/zone-calculate", json=quote_payload())

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is True
    assert public["billing_pallets"] is None
    assert _audit_result(client, public["quote_id"])["source_type"] == "manual_required"


def test_wecom_failure_does_not_affect_quote_return(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(bot_rows=[{"purpose": "quote_success"}])

    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_markdown",
        lambda _self, _content: WeComSendResult(success=False, error="failed", latency_ms=1, status_code=500),
    )

    response = client.post("/quotes/zone-calculate", json={"quote": quote_payload(), "notify_wecom": True})

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is False
    assert public["billing_pallets"] == 3
    assert _audit_result(client, public["quote_id"])["source_type"] == "zone_matrix"


def test_ai_auto_quote_success_notify_sends_ai_quote(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(bot_rows=[{"purpose": "ai_quote"}])
    sent: list[str] = []

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", lambda _message, _client: complete_extraction())
    monkeypatch.setattr("apps.api.services.ai_quote_service._build_guarded_sales_note", lambda _client, quote_result: quote_result.sales_note)
    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_markdown",
        lambda _self, content: sent.append(content) or WeComSendResult(success=True, latency_ms=1, status_code=200),
    )

    response = client.post(
        "/quotes/ai-auto-quote",
        json={"customer_message": "quote this", "notify_wecom": True},
    )

    assert response.status_code == 200
    public = response.json()
    assert public["quote_result"]["manual_review_required"] is False
    assert public["quote_result"]["billing_pallets"] == 3
    assert _audit_result(client, public["quote_result"]["quote_id"])["source_type"] == "zone_matrix"
    assert len(sent) == 1
    assert "AI 自动报价成功" in sent[0]


def test_ai_auto_quote_manual_required_auto_sends_manual_required(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(include_zone_rule=False, bot_rows=[{"purpose": "manual_required"}])
    sent: list[str] = []

    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", lambda _message, _client: complete_extraction())
    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_markdown",
        lambda _self, content: sent.append(content) or WeComSendResult(success=True, latency_ms=1, status_code=200),
    )

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is True
    assert public["quote_result"]["billing_pallets"] is None
    assert _audit_result(client, public["quote_result"]["quote_id"])["source_type"] == "manual_required"
    assert len(sent) == 1
    assert "需人工确认" in sent[0]


def test_manual_task_resolved_notify_sends_resolved(monkeypatch: pytest.MonkeyPatch) -> None:
    client = build_client(include_zone_rule=False, bot_rows=[{"purpose": "manual_resolved"}])
    client.post("/quotes/zone-calculate", json=quote_payload())
    task = client.get("/quotes/manual-tasks").json()[0]
    sent: list[str] = []

    monkeypatch.setattr(
        "apps.api.services.notification_service.WeComBotClient.send_markdown",
        lambda _self, content: sent.append(content) or WeComSendResult(success=True, latency_ms=1, status_code=200),
    )

    response = client.patch(
        f"/quotes/manual-tasks/{task['id']}",
        json={
            "status": "resolved",
            "resolved_price_usd": "250.00",
            "resolved_note": "Confirmed.",
            "notify_wecom": True,
        },
    )

    assert response.status_code == 200
    assert len(sent) == 1
    assert "人工报价已处理" in sent[0]
