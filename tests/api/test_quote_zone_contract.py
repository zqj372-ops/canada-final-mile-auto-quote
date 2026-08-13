from collections.abc import Generator
from datetime import date
from decimal import Decimal
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import APIKey, Base, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.services import quote_service
from tests.api.test_api_keys_auth import SALES_KEY, VIEWER_KEY, build_client as build_auth_client
from tests.api.test_zone_quotes import base_payload, build_client


def configure_ready_status(monkeypatch: pytest.MonkeyPatch, *, test_data: str = "false") -> None:
    values = {
        "QUOTE_TEST_DATA": test_data,
        "QUOTE_SERVICE_VERSION": "0.1.0",
        "QUOTE_RELEASE_ID": "release-20260812-a",
        "QUOTE_RELEASE_HASH": "auto",
        "QUOTE_RULE_VERSION": "zone-rules-20260728",
        "QUOTE_DATA_VERSION": "zone-data-20260728",
        "QUOTE_PUBLISHED_AT": "2026-08-12T10:00:00+00:00",
        "QUOTE_VALID_FROM": "2026-07-28",
        "QUOTE_VALID_TO": "2026-12-31",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)


def preview_payload(**overrides: object) -> dict[str, object]:
    return {
        "tenant_id": "default",
        "origin": "toronto",
        "effective_date": date.today().isoformat(),
        "quote": base_payload(**overrides),
    }


def test_source_status_is_not_ready_without_release_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "QUOTE_TEST_DATA",
        "QUOTE_SERVICE_VERSION",
        "QUOTE_RELEASE_ID",
        "QUOTE_RELEASE_HASH",
        "QUOTE_RULE_VERSION",
        "QUOTE_DATA_VERSION",
        "QUOTE_PUBLISHED_AT",
        "QUOTE_VALID_FROM",
        "QUOTE_VALID_TO",
    ):
        monkeypatch.delenv(key, raising=False)
    client = build_client()

    response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "source-status.v1"
    assert body["system"] == "ai_quote"
    assert body["contract_version"] == "quote-zone.v1"
    assert body["ready"] is False
    assert body["release_id"] is None
    assert body["release_hash"] is None
    assert body["snapshot_hash"]
    assert body["rule_version"] is None
    assert body["data_version"] is None
    assert body["published_at"] is None
    assert any("QUOTE_RELEASE_HASH" in reason for reason in body["reasons"])


def test_source_status_uses_explicit_deployment_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()

    response = client.get("/api/status")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "source-status.v1",
        "system": "ai_quote",
        "ready": True,
        "test_data": False,
        "service_version": "0.1.0",
        "contract_version": "quote-zone.v1",
        "release_id": "release-20260812-a",
        "release_hash": os.environ["QUOTE_RELEASE_HASH"],
        "snapshot_hash": os.environ["QUOTE_RELEASE_HASH"],
        "rule_version": "zone-rules-20260728",
        "data_version": "zone-data-20260728",
        "published_at": "2026-08-12T10:00:00+00:00",
        "reasons": [],
        "supported_operations": ["quote.zone_preview"],
        "valid_from": "2026-07-28",
        "valid_to": "2026-12-31",
    }


def test_source_status_rejects_test_data_as_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch, test_data="true")
    client = build_client()

    response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["test_data"] is True
    assert body["ready"] is False
    assert "test_data_not_authoritative" in body["reasons"]


def test_source_status_rejects_static_release_hash_not_bound_to_db(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()
    monkeypatch.setenv("QUOTE_RELEASE_HASH", "8d69f9dc91f9c75febfbd02d7d5568a29af659ec")

    response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert body["release_hash"] is None
    assert body["snapshot_hash"].startswith("sha256:")
    assert "deployment_config_mismatch:QUOTE_RELEASE_HASH" in body["reasons"]


def test_zone_preview_rejects_static_release_hash_not_bound_to_db(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()
    monkeypatch.setenv("QUOTE_RELEASE_HASH", "8d69f9dc91f9c75febfbd02d7d5568a29af659ec")

    response = client.post("/quotes/zone-preview", json=preview_payload())

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["release_hash"] is None
    assert body["snapshot_hash"].startswith("sha256:")
    assert "deployment_config_mismatch:QUOTE_RELEASE_HASH" in body["reasons"]


def test_source_status_rejects_incomplete_effective_window(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    monkeypatch.delenv("QUOTE_VALID_TO")
    client = build_client()

    response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert "deployment_config_missing:QUOTE_VALID_TO" in body["reasons"]


def test_source_status_rejects_inactive_effective_window(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    monkeypatch.setenv("QUOTE_VALID_FROM", "2999-01-01")
    client = build_client()

    response = client.get("/api/status")

    assert response.status_code == 200
    body = response.json()
    assert body["ready"] is False
    assert "effective_window_not_active:before_valid_from" in body["reasons"]


def test_source_status_uses_existing_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_auth_client()

    missing = client.get("/api/status")
    sales = client.get("/api/status", headers={"X-API-Key": SALES_KEY})

    assert missing.status_code == 401
    assert sales.status_code == 200


def test_zone_preview_reuses_quote_engine_without_writes_or_notifications(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_ready_status(monkeypatch)
    client, spies = build_spy_client()
    side_effect_calls: list[object] = []
    notification_calls: list[object] = []
    monkeypatch.setattr(
        quote_service,
        "record_zone_quote_side_effects",
        lambda *args, **kwargs: side_effect_calls.append((args, kwargs)),
    )
    monkeypatch.setattr(
        quote_service,
        "try_notification",
        lambda *args, **kwargs: notification_calls.append((args, kwargs)),
    )

    response = client.post("/quotes/zone-preview", json=preview_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["quote_id"]
    assert body["quote_version"] == "release-20260812-a:zone-rules-20260728:zone-data-20260728"
    assert body["status"] == "quoted"
    assert body["source_type"] == "zone_matrix"
    assert body["origin"] == "toronto"
    assert body["zone"] == 2
    assert body["billing_pallets"] == 3
    assert body["test_data"] is False
    assert body["manual_review_required"] is False
    assert body["matched_by"] == "fsa_single_zone"
    assert body["fees"]["total"]["amount"] == "212.00"
    assert body["fees"]["total"]["currency"] == "USD"
    assert body["rule_version"] == "zone-rules-20260728"
    assert body["data_version"] == "zone-data-20260728"
    assert body["valid_from"] == "2026-07-28"
    assert body["valid_to"] == "2026-12-31"
    assert body["source_ref"] == "zone_price_matrix"
    assert body["release_id"] == "release-20260812-a"
    assert body["snapshot_hash"] == body["release_hash"]
    assert "address_line" not in body
    assert "internal_note" not in body
    assert "base_cost_cad" not in body
    assert side_effect_calls == []
    assert notification_calls == []
    assert spies[0].calls == {"add": 0, "flush": 0, "commit": 0}


def test_zone_preview_is_unavailable_for_test_data(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch, test_data="true")
    client = build_client()

    response = client.post("/quotes/zone-preview", json=preview_payload())

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["test_data"] is True
    assert body["fees"] == {}


def test_zone_preview_requires_explicit_context(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()

    response = client.post("/quotes/zone-preview", json={"quote": base_payload()})

    assert response.status_code == 422


def test_zone_preview_api_key_auth_does_not_commit_auth_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_ready_status(monkeypatch)
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client, spies = build_spy_auth_client()

    response = client.post(
        "/quotes/zone-preview",
        json=preview_payload(),
        headers={"X-API-Key": SALES_KEY},
    )

    assert response.status_code == 200
    assert spies[0].calls["add"] == 0
    assert spies[0].calls["flush"] == 0
    assert spies[0].calls["commit"] == 0
    assert spies[0].session.scalar(select(APIKey.last_used_at)) is None


def test_zone_preview_rejects_api_key_tenant_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client, _spies = build_spy_auth_client(tenant_id="tenant-a")

    response = client.post(
        "/quotes/zone-preview",
        json=preview_payload(),
        headers={"X-API-Key": SALES_KEY},
    )

    assert response.status_code == 403


def test_zone_preview_fails_closed_when_source_data_hash_switches(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()
    calls = 0

    def changing_hash(_db):
        nonlocal calls
        calls += 1
        return "sha256:before" if calls == 1 else "sha256:after"

    monkeypatch.setattr(quote_service, "source_data_hash", changing_hash)

    response = client.post("/quotes/zone-preview", json=preview_payload())

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["fees"] == {}
    assert "source_data_changed_during_calculation" in body["reasons"]


def test_zone_preview_returns_no_price_for_missing_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()

    response = client.post(
        "/quotes/zone-preview",
        json=preview_payload(postal_code="N0A 1M0", city="Ohsweken", province="ON"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "manual_required"
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["fees"] == {}
    assert "total_price_usd" not in body


def test_zone_preview_returns_no_price_for_zone_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client(
        postal_records=[{"postal_code": "N0A 1M0", "preferred_city": "Ohsweken", "province": "ON"}],
        zone_rules=[
            {
                "postal_prefix": "N0A",
                "city": "HAGERSVILLE",
                "province": "ON",
                "origin": "toronto",
                "zone": 5,
                "match_level": "test",
                "note": "",
            },
            {
                "postal_prefix": "N0A",
                "city": "OHSWEKEN",
                "province": "ON",
                "origin": "toronto",
                "zone": 6,
                "match_level": "test",
                "note": "",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-preview",
        json={
            **preview_payload(
                address_line="1595 Sour Springs Rd",
                postal_code="N0A 1M0",
                city="Hagersville",
                province="ON",
                requires_appointment=False,
            ),
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "manual_required"
    assert body["matched_by"] == "split_record_conflict"
    assert body["manual_review_required"] is True
    assert body["fees"] == {}


def test_zone_preview_requires_existing_authentication(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    client = build_auth_client()

    missing = client.post("/quotes/zone-preview", json=preview_payload())
    viewer = client.post(
        "/quotes/zone-preview",
        json=preview_payload(),
        headers={"X-API-Key": VIEWER_KEY},
    )
    sales = client.post(
        "/quotes/zone-preview",
        json=preview_payload(),
        headers={"X-API-Key": SALES_KEY},
    )

    assert missing.status_code == 401
    assert viewer.status_code == 403
    assert sales.status_code == 200


def test_zone_preview_fails_closed_when_versions_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_ready_status(monkeypatch)
    client = build_client()
    original = quote_service.get_source_status
    calls = 0

    def changing_status(_db=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            monkeypatch.setenv("QUOTE_RULE_VERSION", "zone-rules-20260812")
        return original(_db)

    monkeypatch.setattr(quote_service, "get_source_status", changing_status)

    response = client.post("/quotes/zone-preview", json=preview_payload())

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "unavailable"
    assert body["manual_review_required"] is True
    assert body["fees"] == {}
    assert "source_version_changed_during_calculation" in body["reasons"]


class SessionSpy:
    def __init__(self, session: Session):
        self.session = session
        self.calls = {"add": 0, "flush": 0, "commit": 0}

    def add(self, instance, _warn=True):
        self.calls["add"] += 1
        return self.session.add(instance, _warn=_warn)

    def flush(self, *args, **kwargs):
        self.calls["flush"] += 1
        return self.session.flush(*args, **kwargs)

    def commit(self):
        self.calls["commit"] += 1
        return self.session.commit()

    def __getattr__(self, name: str):
        return getattr(self.session, name)


def build_spy_client() -> tuple[TestClient, list[SessionSpy]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
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
        session.commit()
        if os.getenv("QUOTE_RELEASE_HASH") == "auto":
            from apps.api.services.source_status_service import source_data_hash

            os.environ["QUOTE_RELEASE_HASH"] = source_data_hash(session)

    spies: list[SessionSpy] = []

    def override_get_db() -> Generator[SessionSpy]:
        with TestingSessionLocal() as session:
            spy = SessionSpy(session)
            spies.append(spy)
            yield spy

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), spies


def build_spy_auth_client(
    *, tenant_id: str = "default", scopes: list[str] | None = None
) -> tuple[TestClient, list[SessionSpy]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    from apps.api.db.models import APIKey
    from apps.api.security.api_keys import hash_api_key

    with TestingSessionLocal() as session:
        session.add(
            APIKey(
                name="Sales",
                key_hash=hash_api_key(SALES_KEY),
                role="sales",
                enabled=True,
                tenant_id=tenant_id,
                scopes=scopes or ["quote:preview"],
            )
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
        session.commit()
        if os.getenv("QUOTE_RELEASE_HASH") == "auto":
            from apps.api.services.source_status_service import source_data_hash

            os.environ["QUOTE_RELEASE_HASH"] = source_data_hash(session)

    spies: list[SessionSpy] = []

    def override_get_db() -> Generator[SessionSpy]:
        with TestingSessionLocal() as session:
            spy = SessionSpy(session)
            spies.append(spy)
            yield spy

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), spies


def teardown_module() -> None:
    app.dependency_overrides.clear()
