from collections.abc import Generator
from datetime import date, timedelta
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.auth import CurrentActor
from apps.api.db.models import APIKey, Base, FCLRateCard, QuoteRuleConfig, SalesQuoteRecord
from apps.api.db.repositories.fcl_rate_card_repository import FCLQuoteConfigRepository
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.api_keys import hash_api_key
from packages.quote_engine.fcl import (
    FCLExchangeRate,
    FCLFeeLine,
    FCLQuoteConfig,
    FCLRateCardPayload,
    default_fcl_quote_config,
)


ADMIN_KEY = "fcl_admin_key"
SALES_KEY = "fcl_sales_key"


def build_client(*, publish_config: bool = True, rate_card_status: str = "published") -> tuple[TestClient, sessionmaker[Session]]:
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
        card = FCLRateCard(
            pol="CNSHA",
            pod="CAVAN",
            container_type="40HQ",
            service_scope="port-to-port",
            effective_from=date.today() - timedelta(days=1),
            effective_to=date.today() + timedelta(days=30),
            priority=100,
            status=rate_card_status,
            enabled=True,
            fee_lines=[
                FCLFeeLine(
                    item_name="海运费",
                    unit="container",
                    currency="USD",
                    sales_unit_price=Decimal("1200.00"),
                    pricing_status="auto",
                    display_mode="both",
                ).model_dump(mode="json"),
                FCLFeeLine(
                    item_name="文件费",
                    unit="shipment",
                    currency="CAD",
                    sales_unit_price=Decimal("50.00"),
                    pricing_status="auto",
                    display_mode="both",
                ).model_dump(mode="json"),
                FCLFeeLine(
                    item_name="目的港杂费（隐藏包含）",
                    unit="shipment",
                    currency="CNY",
                    sales_unit_price=Decimal("200.00"),
                    pricing_status="auto",
                    display_mode="hiddenIncluded",
                ).model_dump(mode="json"),
            ],
        )
        session.add(card)
        session.commit()
        if publish_config:
            config = default_fcl_quote_config()
            config = config.model_copy(
                update={
                    "port_aliases": {"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
                    "container_aliases": {"40HC": "40HQ"},
                    "settlement_currency": None,
                    "terms": ["测试条款"],
                }
            )
            repository = FCLQuoteConfigRepository(session)
            repository.save_draft(config)
            repository.publish_draft(CurrentActor(user_id=None, api_key_id=None, name="admin", role="admin"))

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def confirmed_draft() -> dict[str, object]:
    return {
        "customer_name": "ABC Trading Ltd.",
        "contact": "张三 / zhang@example.com",
        "customer_type": "importer",
        "pol": "Shanghai",
        "pod": "Vancouver",
        "containers": [{"container_type": "40HC", "quantity": 2}],
        "cargo_name": "五金",
        "cargo_items": [
            {
                "quantity": 4,
                "length": "100",
                "width": "50",
                "height": "50",
                "dimension_unit": "cm",
                "weight": "100",
                "weight_unit": "kg",
            }
        ],
        "special_attributes": ["general_cargo"],
        "ready_date": date.today().isoformat(),
        "importer_exists": "yes",
        "service_scope": "port-to-port",
        "confidence": 100,
        "extraction_notes": [],
    }


def test_fcl_auto_quote_prices_deterministically_and_strips_internal_fields() -> None:
    client, session_local = build_client()

    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "整柜询价：POL 上海 → POD 温哥华，40HC x2，普货，port-to-port，货名五金，每件100kg",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"]["manual_review_required"] is False, body["quote_result"]["manual_reasons"]
    assert body["quote_result"]["totals_by_currency"] == {"USD": "2400.00", "CAD": "50.00", "CNY": "200.00"}
    assert body["quote_result"]["fee_items"][0]["amount"] == "2400.00"
    assert "cost_unit_price" not in response.text
    assert "vendor" not in response.text.lower()
    assert "internal_note" not in response.text

    records = client.get("/quotes/sales-records", headers={"X-API-Key": SALES_KEY})
    assert records.status_code == 200
    assert records.json()[0]["quote_type"] == "fcl"
    assert "cost_unit_price" not in records.text
    assert "vendor" not in records.text.lower()
    assert "internal_note" not in records.text


def test_fcl_draft_rate_card_and_missing_fields_fail_closed() -> None:
    client, _ = build_client(rate_card_status="draft")

    response = client.post(
        "/quotes/fcl-auto-quote",
        json={
            "raw_message": "整柜询价：40HC x1",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": True,
        },
    )

    body = response.json()
    assert response.status_code == 200
    assert body["manual_review_required"] is True
    assert body["quote_result"]["totals_by_currency"] == {}
    assert "no_published_rate_card:40HQ" in body["quote_result"]["manual_reasons"]


def test_fcl_admin_config_draft_publish_and_rate_card_lifecycle(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client, _ = build_client(publish_config=False)

    assert client.post("/quote-configs/fcl/publish", headers={"X-API-Key": ADMIN_KEY}).status_code == 200
    assert client.get("/quote-configs/fcl", headers={"X-API-Key": SALES_KEY}).status_code == 403

    cards = client.get("/quote-configs/fcl-rate-cards", headers={"X-API-Key": ADMIN_KEY})
    assert cards.status_code == 200
    assert cards.json()[0]["status"] == "published"


def test_fcl_quote_snapshot_does_not_drift_after_reprice() -> None:
    client, session_local = build_client()

    first = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "整柜询价：POL 上海 → POD 温哥华，40HC x2，普货，port-to-port",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": True,
        },
    )
    assert first.status_code == 200
    assert first.json()["quote_result"]["totals_by_currency"] == {
        "USD": "2400.00",
        "CAD": "50.00",
        "CNY": "200.00",
    }

    records = client.get("/quotes/sales-records", headers={"X-API-Key": SALES_KEY})
    record_id = records.json()[0]["id"]

    # Admin reprices by publishing a new draft rate card and config v2; published cards stay immutable.
    new_card = {
        "pol": "CNSHA",
        "pod": "CAVAN",
        "container_type": "40HQ",
        "service_scope": "port-to-port",
        "effective_from": (date.today() - timedelta(days=1)).isoformat(),
        "effective_to": (date.today() + timedelta(days=30)).isoformat(),
        "priority": 90,
        "source": "reprice-v2",
        "fee_lines": [
            {
                "item_name": "海运费",
                "unit": "container",
                "currency": "USD",
                "sales_unit_price": "1500.00",
                "pricing_status": "auto",
                "display_mode": "both",
            },
            {
                "item_name": "文件费",
                "unit": "shipment",
                "currency": "CAD",
                "sales_unit_price": "50.00",
                "pricing_status": "auto",
                "display_mode": "both",
            },
            {
                "item_name": "目的港杂费（隐藏包含）",
                "unit": "shipment",
                "currency": "CNY",
                "sales_unit_price": "200.00",
                "pricing_status": "auto",
                "display_mode": "hiddenIncluded",
            },
        ],
    }
    created = client.post(
        "/quote-configs/fcl-rate-cards",
        headers={"X-API-Key": ADMIN_KEY},
        json=new_card,
    )
    assert created.status_code == 201, created.text
    card_id = created.json()["id"]
    published_card = client.post(
        f"/quote-configs/fcl-rate-cards/{card_id}/publish",
        headers={"X-API-Key": ADMIN_KEY},
    )
    assert published_card.status_code == 200, published_card.text

    config = default_fcl_quote_config().model_copy(
        update={
            "port_aliases": {"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
            "container_aliases": {"40HC": "40HQ"},
            "settlement_currency": None,
            "terms": ["测试条款 v2"],
        }
    )
    saved = client.put(
        "/quote-configs/fcl/draft",
        headers={"X-API-Key": ADMIN_KEY},
        json=config.model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    published = client.post("/quote-configs/fcl/publish", headers={"X-API-Key": ADMIN_KEY})
    assert published.status_code == 200, published.text
    assert published.json()["published_version"] == 2

    second = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "整柜询价：POL 上海 → POD 温哥华，40HC x2，普货，port-to-port",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": True,
        },
    )
    assert second.status_code == 200
    assert second.json()["quote_result"]["totals_by_currency"] == {
        "USD": "3000.00",
        "CAD": "50.00",
        "CNY": "200.00",
    }

    with session_local() as session:
        old = session.get(SalesQuoteRecord, record_id)
        assert old is not None
        assert old.snapshot_json["config_version"] == 1
        assert old.result_json["quote_result"]["totals_by_currency"]["USD"] == "2400.00"
        assert old.snapshot_json["fee_items"][0]["amount"] == "2400.00"


def test_fcl_quote_fails_closed_when_exchange_rate_expired() -> None:
    client, _ = build_client(publish_config=False)

    config = default_fcl_quote_config().model_copy(
        update={
            "port_aliases": {"SHANGHAI": "CNSHA", "VANCOUVER": "CAVAN"},
            "container_aliases": {"40HC": "40HQ"},
            "settlement_currency": "USD",
            "exchange_rates": [
                FCLExchangeRate(
                    from_currency="CAD",
                    to_currency="USD",
                    rate=Decimal("1.30"),
                    effective_from=date.today() - timedelta(days=10),
                    effective_to=date.today() - timedelta(days=1),
                )
            ],
            "terms": ["测试条款"],
        }
    )
    saved = client.put(
        "/quote-configs/fcl/draft",
        headers={"X-API-Key": ADMIN_KEY},
        json=config.model_dump(mode="json"),
    )
    assert saved.status_code == 200, saved.text
    published = client.post("/quote-configs/fcl/publish", headers={"X-API-Key": ADMIN_KEY})
    assert published.status_code == 200, published.text

    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "整柜询价：POL 上海 → POD 温哥华，40HC x2，普货，port-to-port",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manual_review_required"] is True
    assert "exchange_rate_missing_or_expired:CAD->USD" in body["quote_result"]["manual_reasons"]
    assert body["quote_result"]["totals_by_currency"] == {}
    assert body["quote_result"]["converted_total"] is None
    assert all(item["amount"] is None for item in body["quote_result"]["fee_items"])
    assert "人工复核" in body["customer_reply"]


def test_fcl_api_rejects_negative_quantities_prices_and_invalid_currency() -> None:
    client, _ = build_client()

    bad = confirmed_draft()
    bad["containers"] = [{"container_type": "40HQ", "quantity": -1}]
    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "整柜询价",
            "confirmed_fields": bad,
            "auto_submit_when_complete": True,
        },
    )
    assert response.status_code == 422

    negative_price = {
        "pol": "CNSHA",
        "pod": "CAVAN",
        "container_type": "40HQ",
        "service_scope": "port-to-port",
        "fee_lines": [
            {
                "item_name": "海运费",
                "unit": "container",
                "currency": "EUR",
                "sales_unit_price": "-1",
                "pricing_status": "auto",
                "display_mode": "both",
            }
        ],
    }
    response = client.post(
        "/quote-configs/fcl-rate-cards",
        headers={"X-API-Key": ADMIN_KEY},
        json=negative_price,
    )
    assert response.status_code == 422


def test_fcl_form_only_submission_works_and_precheck_creates_no_record() -> None:
    client, _ = build_client()

    precheck = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": False,
        },
    )
    assert precheck.status_code == 200
    assert precheck.json()["quote_result"] is None

    records = client.get("/quotes/sales-records", headers={"X-API-Key": SALES_KEY})
    assert records.status_code == 200
    assert records.json() == []

    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "",
            "confirmed_fields": confirmed_draft(),
            "auto_submit_when_complete": True,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["manual_review_required"] is False, body["quote_result"]["manual_reasons"]
    assert body["quote_result"]["totals_by_currency"] == {
        "USD": "2400.00",
        "CAD": "50.00",
        "CNY": "200.00",
    }

    records = client.get("/quotes/sales-records", headers={"X-API-Key": SALES_KEY})
    assert len(records.json()) == 1
    assert records.json()[0]["customer_message"] == "POL Shanghai；POD Vancouver；40HC x2；port-to-port；货名 五金"


def test_fcl_missing_reference_blocking_field_fails_closed() -> None:
    client, _ = build_client()

    draft = confirmed_draft()
    del draft["customer_type"]
    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "",
            "confirmed_fields": draft,
            "auto_submit_when_complete": True,
        },
    )
    body = response.json()
    assert body["manual_review_required"] is True
    assert "missing:customer_type" in body["quote_result"]["manual_reasons"]
    assert body["quote_result"]["totals_by_currency"] == {}


def test_fcl_door_delivery_requires_destination_details() -> None:
    client, _ = build_client()

    draft = confirmed_draft()
    draft["service_scope"] = "door-to-door"
    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "",
            "confirmed_fields": draft,
            "auto_submit_when_complete": True,
        },
    )
    body = response.json()
    reasons = body["quote_result"]["manual_reasons"]
    assert "missing:destination_postal_code" in reasons
    assert "missing:destination_address" in reasons
    assert "missing:address_type" in reasons


def test_fcl_reference_conditions_trigger_manual_review() -> None:
    client, _ = build_client()

    draft = confirmed_draft()
    draft.update(
        {
            "importer_exists": "no",
            "tax_included": "compare",
            "deadline_strictness": "hard",
            "special_attributes": ["wood"],
            "wood_packaging": "unknown",
            "stackable": False,
        }
    )
    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={
            "raw_message": "",
            "confirmed_fields": draft,
            "auto_submit_when_complete": True,
        },
    )
    body = response.json()
    reasons = body["quote_result"]["manual_reasons"]
    assert "hard_deadline_manual_review" in reasons
    assert "importer_condition_manual_review" in reasons
    assert "wood_packaging_pending" in reasons
    assert "non_stackable_manual_review" in reasons
