from collections.abc import Generator
from decimal import Decimal

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import (
    APIKey,
    Base,
    ManualQuoteTask,
    PostalCodeCityLookup,
    SalesQuoteRecord,
    User,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.api_keys import API_KEY_PREFIX, hash_api_key
from apps.api.security.passwords import hash_password


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

        sales_user = User(
            username="sales@example.com",
            display_name="Sales User",
            password_hash=hash_password("password123"),
            role="sales",
            enabled=True,
        )
        other_sales_user = User(
            username="other@example.com",
            display_name="Other Sales",
            password_hash=hash_password("password123"),
            role="sales",
            enabled=True,
        )
        session.add_all([sales_user, other_sales_user])
        session.flush()
        session.add_all(
            [
                SalesQuoteRecord(
                    quote_id="quote_sales_user",
                    actor_user_id=sales_user.id,
                    actor_name=sales_user.display_name,
                    actor_role=sales_user.role,
                    status="quoted",
                    customer_message="sales user message",
                    customer_reply="reply",
                    request_json={},
                    result_json={
                        "manual_review_required": False,
                        "missing_fields": [],
                        "extraction": {"postal_code": "L4K 2N2", "piece_count": 3},
                        "quote_result": {
                            "quote_id": "quote_sales_user",
                            "source_type": "zone_matrix",
                            "city": "Concord",
                            "province": "ON",
                            "zone": 2,
                            "billing_pallets": 3,
                            "total_price_usd": "120.00",
                            "risk_tags": [],
                            "confidence": 100,
                        },
                    },
                ),
                SalesQuoteRecord(
                    quote_id="quote_other_user",
                    actor_user_id=other_sales_user.id,
                    actor_name=other_sales_user.display_name,
                    actor_role=other_sales_user.role,
                    status="quoted",
                    customer_message="other user message",
                    customer_reply="reply",
                    request_json={},
                    result_json={
                        "manual_review_required": False,
                        "missing_fields": [],
                        "extraction": {"postal_code": "L4K 2N2", "piece_count": 3},
                        "quote_result": {
                            "quote_id": "quote_other_user",
                            "source_type": "zone_matrix",
                            "city": "Concord",
                            "province": "ON",
                            "zone": 2,
                            "billing_pallets": 3,
                            "total_price_usd": "120.00",
                            "risk_tags": [],
                            "confidence": 100,
                        },
                    },
                ),
            ]
        )

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
    public = quote_response.json()
    assert set(public) == {
        "quote_id",
        "origin",
        "zone",
        "billing_pallets",
        "total_price_usd",
        "sales_note",
        "manual_review_required",
        "public_flags",
    }
    assert public["origin"] == "toronto"
    assert public["zone"] == 2
    assert public["billing_pallets"] == 3
    audit = client.get(f"/quotes/audit/{public['quote_id']}", headers=headers(ADMIN_KEY))
    assert audit.status_code == 200
    assert audit.json()["result_json"]["source_type"] == "zone_matrix"
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


def test_backoffice_auth_allows_admin_operator_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    for api_key, role in [
        (ADMIN_KEY, "admin"),
        (OPERATOR_KEY, "operator"),
        (VIEWER_KEY, "viewer"),
    ]:
        response = client.get("/auth/backoffice", headers=headers(api_key))
        assert response.status_code == 200
        assert response.json()["role"] == role


def test_backoffice_auth_rejects_sales_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.get("/auth/backoffice", headers=headers(SALES_KEY))

    assert response.status_code == 403


def test_auth_me_allows_sales_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.get("/auth/me", headers=headers(SALES_KEY))

    assert response.status_code == 200
    assert response.json()["role"] == "sales"


def test_user_can_login_and_use_bearer_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    login_response = client.post(
        "/auth/login",
        json={"username": "sales@example.com", "password": "password123"},
    )
    token = login_response.json()["access_token"]
    me_response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})

    assert login_response.status_code == 200
    assert me_response.status_code == 200
    assert me_response.json()["name"] == "Sales User"
    assert me_response.json()["role"] == "sales"


def test_sales_user_reads_only_own_quote_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    login_response = client.post(
        "/auth/login",
        json={"username": "sales@example.com", "password": "password123"},
    )
    token = login_response.json()["access_token"]
    records_response = client.get(
        "/quotes/sales-records",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert records_response.status_code == 200
    records = records_response.json()
    assert [record["quote_id"] for record in records] == ["quote_sales_user"]


def test_manual_price_override_requires_second_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/sales-records/1/manual-price",
        json={"total_price_usd": 180, "override_note": "confirmed with vendor", "confirmed": False},
        headers=headers(ADMIN_KEY),
    )

    assert response.status_code == 400


def test_sales_cannot_override_quote_record_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/sales-records/1/manual-price",
        json={"total_price_usd": 180, "override_note": "confirmed with vendor", "confirmed": True},
        headers=headers(SALES_KEY),
    )

    assert response.status_code == 403


def test_admin_can_override_quote_record_price(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/sales-records/1/manual-price",
        json={
            "total_price_usd": 180.25,
            "override_note": "已与供应商确认，按人工价处理",
            "customer_reply": "客户报价 USD 180.25",
            "confirmed": True,
        },
        headers=headers(ADMIN_KEY),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "quoted"
    assert body["total_price_usd"] == "180.25"
    assert body["source_type"] == "manual_override"
    assert body["customer_reply"] == "客户报价 USD 180.25"
    assert body["result_json"]["manual_override"]["previous_total_price_usd"] == "120.00"
    assert body["result_json"]["manual_override"]["actor_name"] == "Admin"


def test_admin_can_override_quote_record_price_by_quote_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/sales-records/by-quote/quote_sales_user/manual-price",
        json={
            "total_price_usd": 181.25,
            "override_note": "后台审计页人工确认价格",
            "confirmed": True,
        },
        headers=headers(ADMIN_KEY),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["quote_id"] == "quote_sales_user"
    assert body["status"] == "quoted"
    assert body["total_price_usd"] == "181.25"
    assert body["source_type"] == "manual_override"
    assert body["result_json"]["manual_override"]["previous_total_price_usd"] == "120.00"


def test_quote_id_manual_price_override_requires_second_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/sales-records/by-quote/quote_sales_user/manual-price",
        json={"total_price_usd": 181.25, "override_note": "missing second confirmation", "confirmed": False},
        headers=headers(ADMIN_KEY),
    )

    assert response.status_code == 400


def test_sales_cannot_override_quote_record_price_by_quote_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_client()

    response = client.patch(
        "/quotes/sales-records/by-quote/quote_sales_user/manual-price",
        json={"total_price_usd": 181.25, "override_note": "sales should not override", "confirmed": True},
        headers=headers(SALES_KEY),
    )

    assert response.status_code == 403
