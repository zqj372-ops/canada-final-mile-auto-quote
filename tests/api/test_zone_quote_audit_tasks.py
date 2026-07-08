from decimal import Decimal
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, LearnedQuoteRule, PostalCodeCityLookup, QuoteRuleConfig, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.services.hermes_agent_correction_service import AgentDecision, HermesAgentCorrectionService


def build_client(
    *,
    include_zone_rule: bool = True,
    config_rows: list[dict[str, object]] | None = None,
    learned_rows: list[dict[str, object]] | None = None,
    zone_rule_rows: list[dict[str, object]] | None = None,
    price_rows: list[dict[str, object]] | None = None,
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
        for row in zone_rule_rows or []:
            session.add(ZoneLookupRule(**row))
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
        for row in price_rows or []:
            session.add(ZonePriceMatrix(**row))
        for row in config_rows or []:
            session.add(QuoteRuleConfig(**row))
        for row in learned_rows or []:
            session.add(LearnedQuoteRule(**row))
        session.commit()

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def payload(**overrides: object) -> dict[str, object]:
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


def test_zone_calculate_success_writes_audit_log() -> None:
    client = build_client()

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    audit = client.get(f"/quotes/audit/{quote['quote_id']}")

    assert audit.status_code == 200
    body = audit.json()
    assert body["quote_id"] == quote["quote_id"]
    assert body["source_type"] == "zone_matrix"
    assert body["postal_prefix"] == "L4K"
    assert body["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False


def test_manual_required_writes_audit_log() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    audit = client.get(f"/quotes/audit/{quote['quote_id']}").json()

    assert quote["source_type"] == "manual_required"
    assert audit["quote_id"] == quote["quote_id"]
    assert audit["manual_review_required"] is True
    assert audit["total_price_usd"] is None


def test_manual_required_creates_manual_quote_task() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    tasks = client.get("/quotes/manual-tasks").json()

    assert len(tasks) == 1
    assert tasks[0]["quote_id"] == quote["quote_id"]
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["reason"] == quote["matched_rule"]


def test_error_summary_reports_manual_required_and_recent_tasks() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    response = client.get("/quotes/error-summary")

    assert response.status_code == 200
    body = response.json()
    assert body["window_label"] == "近24小时"
    assert body["total_audit_count"] == 1
    assert body["daily_total_audit_count"] == 1
    assert body["manual_required_audit_count"] == 1
    assert body["daily_manual_required_audit_count"] == 1
    assert body["pending_manual_task_count"] == 1
    assert body["daily_pending_manual_task_count"] == 1
    assert body["daily_risk_tag_counts"] == [{"tag": "zone_not_found", "label": "未命中邮编分区", "count": 1}]
    assert body["risk_tag_counts"] == [{"tag": "zone_not_found", "label": "未命中邮编分区", "count": 1}]
    assert body["recent_manual_tasks"][0]["quote_id"] == quote["quote_id"]
    assert body["recent_manual_tasks"][0]["reason_zh"]
    assert body["recent_manual_tasks"][0]["risk_tag_labels"] == ["未命中邮编分区"]
    assert body["recent_manual_audits"][0]["quote_id"] == quote["quote_id"]
    assert body["recent_manual_audits"][0]["risk_tag_labels"] == ["未命中邮编分区"]


def test_successful_quote_does_not_create_manual_quote_task() -> None:
    client = build_client()

    client.post("/quotes/zone-calculate", json=payload())
    tasks = client.get("/quotes/manual-tasks").json()

    assert tasks == []


def test_manual_quote_task_can_be_patched() -> None:
    client = build_client(include_zone_rule=False)
    client.post("/quotes/zone-calculate", json=payload())
    task = client.get("/quotes/manual-tasks").json()[0]

    response = client.patch(
        f"/quotes/manual-tasks/{task['id']}",
        json={
            "status": "resolved",
            "assigned_to": "ops@example.com",
            "resolved_price_usd": "250.00",
            "resolved_note": "Confirmed with supplier.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "resolved"
    assert body["assigned_to"] == "ops@example.com"
    assert body["resolved_price_usd"] == "250.00"
    assert body["resolved_note"] == "Confirmed with supplier."


def test_resolved_manual_task_creates_candidate_and_reuses_only_after_approval() -> None:
    client = build_client(include_zone_rule=False)

    first_quote = client.post("/quotes/zone-calculate", json=payload()).json()
    task = client.get("/quotes/manual-tasks").json()[0]
    patch_response = client.patch(
        f"/quotes/manual-tasks/{task['id']}",
        json={
            "status": "resolved",
            "resolved_price_usd": "250.00",
            "resolved_note": "Confirmed one-off price; allow future same FSA/city/pallet reuse.",
        },
    )
    second_quote_before_approval = client.post("/quotes/zone-calculate", json=payload()).json()
    candidates = client.get("/quotes/learning-candidates").json()
    approval = client.post(
        f"/quotes/learning-candidates/{candidates[0]['id']}/approve",
        json={"review_note": "Approved by operator after supplier confirmation."},
    )
    second_quote_after_approval = client.post("/quotes/zone-calculate", json=payload()).json()
    tasks = client.get("/quotes/manual-tasks").json()
    summary = client.get("/quotes/error-summary").json()

    assert first_quote["source_type"] == "manual_required"
    assert patch_response.status_code == 200
    assert second_quote_before_approval["source_type"] == "manual_required"
    assert candidates[0]["status"] == "pending_review"
    assert candidates[0]["resolved_total_price_usd"] == "250.00"
    assert approval.status_code == 200
    assert approval.json()["candidate"]["status"] == "approved"
    assert second_quote_after_approval["source_type"] == "learned_manual_quote"
    assert second_quote_after_approval["manual_review_required"] is False
    assert second_quote_after_approval["total_price_usd"] == "250.00"
    assert second_quote_after_approval["billing_pallets"] == 3
    assert "learned_quote_reused" in second_quote_after_approval["risk_tags"]
    assert len(tasks) == 2
    assert summary["active_learning_rule_count"] == 1
    assert summary["pending_learning_candidate_count"] == 0
    assert summary["approved_learning_candidate_count"] == 1
    assert summary["learning_rule_usage_count"] == 1
    assert summary["recent_learning_rules"][0]["postal_prefix"] == "L4K"
    assert summary["recent_learning_candidates"][0]["postal_prefix"] == "L4K"


def test_resolved_manual_task_learning_respects_billing_pallets() -> None:
    client = build_client(include_zone_rule=False)

    client.post("/quotes/zone-calculate", json=payload())
    task = client.get("/quotes/manual-tasks").json()[0]
    client.patch(
        f"/quotes/manual-tasks/{task['id']}",
        json={"status": "resolved", "resolved_price_usd": "250.00"},
    )
    candidate = client.get("/quotes/learning-candidates").json()[0]
    client.post(f"/quotes/learning-candidates/{candidate['id']}/approve", json={})

    response = client.post(
        "/quotes/zone-calculate",
        json=payload(cbm=1, weight_kg=100, requires_appointment=False),
    )

    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["billing_pallets"] == 1


def test_hermes_agent_corrects_zone_gap_with_validated_zone_matrix(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_agent_decision(self, request, result, evidence):  # noqa: ANN001
        return AgentDecision(
            action="use_zone_matrix",
            confidence=76,
            reason_zh="MB 省份应走 Calgary，证据中存在 Calgary Zone 5 且价格矩阵有 1 托价格。",
            origin="calgary",
            zone=5,
        )

    monkeypatch.setattr(HermesAgentCorrectionService, "_ask_agent", fake_agent_decision)
    client = build_client(
        include_zone_rule=False,
        zone_rule_rows=[
            {
                "postal_prefix": "R4H",
                "city": "HEADINGLEY",
                "province": "MB",
                "origin": "calgary",
                "zone": 5,
                "match_level": "test",
                "note": "MB expected-origin evidence for Hermes Agent.",
            }
        ],
        price_rows=[
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 1,
                "base_price_usd": Decimal("200.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            }
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=payload(
            address_line="27 greyfriars rd",
            postal_code="R3T 3N7",
            city="Winnipeg",
            province="MB",
            cbm=1.98,
            weight_kg=340,
            piece_count=3,
            explicit_pallet_count=1,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["source_type"] == "hermes_agent_correction"
    assert body["manual_review_required"] is False
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["billing_pallets"] == 1
    assert body["base_price_usd"] == "200.00"
    assert body["fuel_usd"] == "70.00"
    assert body["total_price_usd"] == "270.00"
    assert "hermes_agent_correction" in body["risk_tags"]
    assert "hermes_agent_zone_matrix" in body["risk_tags"]


def test_hermes_agent_receives_curated_safe_options_for_postal_gap(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_agent_decision(self, request, result, evidence):  # noqa: ANN001
        safe_options = evidence["curated_safe_options"]
        assert safe_options
        assert safe_options[0]["origin"] == "calgary"
        assert safe_options[0]["zone"] == 5
        assert safe_options[0]["supporting_prefixes"] == ["R2E", "R2P"]
        return AgentDecision(
            action="use_zone_matrix",
            confidence=safe_options[0]["confidence_ceiling"],
            reason_zh="Hermes Agent 采用后端预筛的最近邮编锚点 R2E/R2P，且均为 Calgary Zone 5。",
            origin=safe_options[0]["origin"],
            zone=safe_options[0]["zone"],
        )

    monkeypatch.setattr(HermesAgentCorrectionService, "_ask_agent", fake_agent_decision)
    client = build_client(
        include_zone_rule=False,
        zone_rule_rows=[
            {
                "postal_prefix": "R2C",
                "city": "WINNIPEG",
                "province": "MB",
                "origin": "toronto",
                "zone": 12,
                "match_level": "legacy",
                "note": "legacy wrong-origin Winnipeg row",
            },
            {
                "postal_prefix": "R2E",
                "city": "EAST ST PAUL",
                "province": "MB",
                "origin": "calgary",
                "zone": 5,
                "match_level": "metro",
                "note": "Winnipeg metro expected-origin anchor",
            },
            {
                "postal_prefix": "R2P",
                "city": "WEST ST PAUL",
                "province": "MB",
                "origin": "calgary",
                "zone": 5,
                "match_level": "metro",
                "note": "Winnipeg metro expected-origin anchor",
            },
            {
                "postal_prefix": "R0A",
                "city": "NIVERVILLE",
                "province": "MB",
                "origin": "calgary",
                "zone": 9,
                "match_level": "remote",
                "note": "farther Manitoba anchor should not be preferred",
            },
        ],
        price_rows=[
            {
                "origin": "toronto",
                "zone": 12,
                "billing_pallets": 1,
                "base_price_usd": Decimal("420.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
            {
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 1,
                "base_price_usd": Decimal("240.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
            {
                "origin": "calgary",
                "zone": 9,
                "billing_pallets": 1,
                "base_price_usd": Decimal("395.00"),
                "source": "test",
                "last_updated": "2026-06-03",
            },
        ],
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=payload(
            address_line="27 greyfriars rd",
            postal_code="R3T 3N7",
            city="Winnipeg",
            province="MB",
            cbm=1.98,
            weight_kg=340,
            piece_count=3,
            explicit_pallet_count=1,
            requires_appointment=False,
        ),
    )

    body = response.json()
    assert body["source_type"] == "hermes_agent_correction"
    assert body["manual_review_required"] is False
    assert body["origin"] == "calgary"
    assert body["zone"] == 5
    assert body["base_price_usd"] == "240.00"
    assert body["total_price_usd"] == "324.00"


def test_exact_postal_learned_rule_corrects_zone_quote_at_quote_time() -> None:
    client = build_client(
        learned_rows=[
            {
                "source_task_id": 99,
                "quote_id": "manual-99",
                "scope": "postal_prefix_city",
                "postal_code": "L4K 2N2",
                "postal_prefix": "L4K",
                "city": "CONCORD",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "billing_pallets": 3,
                "total_price_usd": Decimal("250.00"),
                "base_price_usd": Decimal("250.00"),
                "confidence": 72,
                "status": "active",
                "usage_count": 0,
                "note": "Approved exact postal correction.",
            }
        ]
    )

    response = client.post("/quotes/zone-calculate", json=payload())

    body = response.json()
    assert body["source_type"] == "learned_manual_quote"
    assert body["manual_review_required"] is False
    assert body["total_price_usd"] == "250.00"
    assert body["matched_rule"].startswith("learned_manual_quote")
    assert "score 100" in body["matched_rule"]
    assert "hermes_corrective_override" in body["risk_tags"]


def test_prefix_city_learned_rule_does_not_override_clean_zone_quote() -> None:
    client = build_client(
        learned_rows=[
            {
                "source_task_id": 100,
                "quote_id": "manual-100",
                "scope": "postal_prefix_city",
                "postal_code": None,
                "postal_prefix": "L4K",
                "city": "CONCORD",
                "province": "ON",
                "origin": "toronto",
                "zone": 2,
                "billing_pallets": 3,
                "total_price_usd": Decimal("250.00"),
                "base_price_usd": Decimal("250.00"),
                "confidence": 72,
                "status": "active",
                "usage_count": 0,
                "note": "Prefix city rules should not cover clean zone_matrix quotes.",
            }
        ]
    )

    response = client.post("/quotes/zone-calculate", json=payload())

    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["total_price_usd"] != "250.00"


def test_zone_calculate_uses_database_pricing_config() -> None:
    client = build_client(
        config_rows=[
            {"key": "fuel_percent", "value": "10", "description": None},
            {"key": "appointment_fee_usd", "value": "20", "description": None},
        ]
    )

    quote = client.post("/quotes/zone-calculate", json=payload()).json()

    assert quote["fuel_usd"] == "12.00"
    assert quote["accessorials"]["appointment_fee_usd"] == "20.00"
    assert quote["total_price_usd"] == "152.00"
