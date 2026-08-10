from collections.abc import Generator
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, EmailNotificationConfig, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.secrets import encrypt_secret
from packages.email_notifier.client import EmailSendResult


def build_client(
    *,
    include_zone_rule: bool = True,
    email_rows: list[dict[str, object]] | None = None,
) -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
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
        for row in email_rows or []:
            session.add(
                EmailNotificationConfig(
                    name=str(row.get("name", "Ops email")),
                    smtp_host=str(row.get("smtp_host", "smtp.example.invalid")),
                    smtp_port=int(row.get("smtp_port", 587)),
                    username=str(row.get("username", "mailer@example.com")),
                    password_encrypted=encrypt_secret(str(row.get("password", "secret"))),
                    from_email=str(row.get("from_email", "quote@example.com")),
                    from_name=str(row.get("from_name", "Canada Quote")),
                    recipient_emails=list(row.get("recipient_emails", ["ops@example.com"])),
                    use_tls=bool(row.get("use_tls", True)),
                    use_ssl=bool(row.get("use_ssl", False)),
                    purpose=str(row.get("purpose", "general")),
                    enabled=bool(row.get("enabled", True)),
                    is_default=bool(row.get("is_default", False)),
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
    }
    data.update(overrides)
    return data


def test_create_email_config_does_not_return_password() -> None:
    client = build_client()

    response = client.post(
        "/email/configs",
        json={
            "name": "Ops",
            "smtp_host": "smtp.example.invalid",
            "smtp_port": 587,
            "username": "mailer@example.com",
            "password": "smtp-secret",
            "from_email": "quote@example.com",
            "recipient_emails": ["ops@example.com"],
            "purpose": "quote_success",
            "is_default": True,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["has_password"] is True
    assert "password" not in body
    assert "password_encrypted" not in body
    assert "smtp-secret" not in response.text


def test_email_config_test_sends_email(monkeypatch) -> None:
    client = build_client(email_rows=[{"purpose": "general"}])
    sent: list[dict[str, object]] = []

    def fake_send(_self, *, subject: str, body_text: str, to_emails: list[str]) -> EmailSendResult:
        sent.append({"subject": subject, "body_text": body_text, "to_emails": to_emails})
        return EmailSendResult(success=True, latency_ms=8, status_code=None)

    monkeypatch.setattr("apps.api.routes.email_configs.SmtpEmailClient.send", fake_send)

    response = client.post("/email/configs/1/test")

    assert response.status_code == 200
    assert response.json()["success"] is True
    assert sent[0]["subject"] == "[Canada Quote] 邮件通知测试"
    assert sent[0]["to_emails"] == ["ops@example.com"]


def test_zone_calculate_success_notify_sends_email(monkeypatch) -> None:
    client = build_client(email_rows=[{"purpose": "quote_success"}])
    sent: list[dict[str, object]] = []

    def fake_send(_self, *, subject: str, body_text: str, to_emails: list[str]) -> EmailSendResult:
        sent.append({"subject": subject, "body_text": body_text, "to_emails": to_emails})
        return EmailSendResult(success=True, latency_ms=1, status_code=None)

    monkeypatch.setattr("apps.api.services.notification_service.SmtpEmailClient.send", fake_send)

    response = client.post("/quotes/zone-calculate", json={"quote": quote_payload(), "notify_email": True})

    assert response.status_code == 200
    assert response.json()["source_type"] == "zone_matrix"
    assert len(sent) == 1
    assert "报价成功" in str(sent[0]["subject"])
    assert "total_price_usd" in str(sent[0]["body_text"])


def test_manual_required_auto_sends_email(monkeypatch) -> None:
    client = build_client(include_zone_rule=False, email_rows=[{"purpose": "manual_required"}])
    sent: list[dict[str, object]] = []

    def fake_send(_self, *, subject: str, body_text: str, to_emails: list[str]) -> EmailSendResult:
        sent.append({"subject": subject, "body_text": body_text, "to_emails": to_emails})
        return EmailSendResult(success=True, latency_ms=1, status_code=None)

    monkeypatch.setattr("apps.api.services.notification_service.SmtpEmailClient.send", fake_send)

    response = client.post("/quotes/zone-calculate", json=quote_payload())

    assert response.status_code == 200
    assert response.json()["source_type"] == "manual_required"
    assert len(sent) == 1
    assert "需要人工确认" in str(sent[0]["subject"])
