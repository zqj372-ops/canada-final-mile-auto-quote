from decimal import Decimal
from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import (
    Base,
    HermesLearningCandidate,
    LearnedQuoteRule,
    PostalCodeCityLookup,
    QuoteRuleConfig,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.session import get_db
from apps.api.main import app
from packages.ai_assistant.model_client import AIResponse
from tests.api.test_zone_quotes import _LegacyZoneTestClient


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
    return _LegacyZoneTestClient(app)


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
    if "handling_units" not in data:
        longest = data.get("longest_side_cm")
        longest_value = Decimal(str(longest)) if longest is not None else Decimal("100")
        if longest_value < Decimal("240"):
            cbm = Decimal(str(data.get("cbm") or "0"))
            weight = Decimal(str(data.get("weight_kg") or "0"))
            target = max(
                1,
                int((cbm / Decimal("2")).to_integral_value(rounding="ROUND_CEILING")),
                int((weight / Decimal("500")).to_integral_value(rounding="ROUND_CEILING")),
            )
            explicit = data.get("explicit_pallet_count")
            if isinstance(explicit, int) and explicit > target:
                target = explicit
            data["handling_units"] = [
                {
                    "quantity": target,
                    "packaging_type": str(data.get("packaging_type") or "carton"),
                    "length_cm": "120",
                    "width_cm": "100",
                    "height_cm": str(cbm * Decimal("1000000") / (Decimal(target) * Decimal("12000")) if cbm > 0 else Decimal("100")),
                    "unit_weight_kg": str(weight / Decimal(target) if weight > 0 else Decimal("1")),
                    "contained_customer_pieces": int(data.get("piece_count") or 1),
                }
            ]
    return data


def test_zone_calculate_success_writes_audit_log() -> None:
    client = build_client()

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    audit = client.get(f"/quotes/audit/{quote['quote_id']}")

    assert audit.status_code == 200
    body = audit.json()
    assert body["quote_id"] == quote["quote_id"]
    assert len(body["quote_id"]) == 15
    assert body["source_type"] == "zone_matrix"
    assert body["postal_prefix"] == "L4K"
    assert body["total_price_usd"] == "212.00"
    assert body["manual_review_required"] is False
    assert body["result_json"]["internal_trace"]["calculator"]["totals"]["billing_pallets"] == 3
    assert body["result_json"]["internal_trace"]["handling_units"][0]["length_cm"] == "120"
    assert body["quote_logic"]["status"] == "quoted"
    assert "Zone 价格矩阵" in body["quote_logic"]["price_source"]

    audits = client.get("/quotes/audits").json()
    assert audits[0]["quote_id"] == quote["quote_id"]

    diagnostics = client.get(f"/quotes/hermes-diagnostics?quote_id={quote['quote_id']}").json()
    assert len(diagnostics) == 1
    diagnostic_package = diagnostics[0]["diagnostic_package"]
    assert diagnostics[0]["quote_status"] == "quoted"
    assert diagnostic_package["quote_result"]["source_type"] == "zone_matrix"
    assert diagnostic_package["price_matrix"]["exact_price_found"] is True


def test_manual_required_writes_audit_log() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    audit = client.get(f"/quotes/audit/{quote['quote_id']}").json()

    assert quote["source_type"] == "manual_required"
    assert audit["quote_id"] == quote["quote_id"]
    assert audit["manual_review_required"] is True
    assert audit["total_price_usd"] is None
    assert audit["quote_logic"]["status"] == "manual_required"
    assert "核对" in audit["quote_logic"]["next_action"]


def test_manual_required_creates_manual_quote_task() -> None:
    client = build_client(include_zone_rule=False)

    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    tasks = client.get("/quotes/manual-tasks").json()

    assert len(tasks) == 1
    assert tasks[0]["quote_id"] == quote["quote_id"]
    assert tasks[0]["status"] == "pending"
    assert tasks[0]["reason"] == quote["matched_rule"]
    assert tasks[0]["result_json"]["internal_trace"]["calculator"]["risk_tags"] == []


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


def test_legacy_candidate_with_oversize_risk_cannot_be_approved() -> None:
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
    client = _LegacyZoneTestClient(app)

    client.post("/quotes/zone-calculate", json=payload())
    task = client.get("/quotes/manual-tasks").json()[0]
    client.patch(
        f"/quotes/manual-tasks/{task['id']}",
        json={"status": "resolved", "resolved_price_usd": "250.00"},
    )
    candidate_id = client.get("/quotes/learning-candidates").json()[0]["id"]

    # Simulate a candidate created before the oversize gate existed: inject a
    # hard handling-unit risk after creation.
    with TestingSessionLocal() as session:
        record = session.get(HermesLearningCandidate, candidate_id)
        assert record is not None
        record.risk_tags = list(record.risk_tags) + ["handling_units_missing"]
        session.commit()

    response = client.post(
        f"/quotes/learning-candidates/{candidate_id}/approve",
        json={"review_note": "Legacy candidate review."},
    )

    assert response.status_code == 422
    assert "禁止直接晋升" in response.json()["detail"]
    candidate = client.get(f"/quotes/learning-candidates/{candidate_id}").json()
    assert candidate["status"] == "pending_review"


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
    assert body["billing_pallets"] is None
    audit = client.get(f"/quotes/audit/{body['quote_id']}").json()["result_json"]
    assert audit["billing_pallets"] == 1


def test_zone_gap_creates_hermes_diagnostic_without_changing_quote() -> None:
    client = build_client(
        include_zone_rule=False,
        zone_rule_rows=[
            {
                "postal_prefix": "R3A",
                "city": "HEADINGLEY",
                "province": "MB",
                "origin": "calgary",
                "zone": 5,
                "match_level": "test",
                "note": "MB expected-origin evidence for Hermes diagnostics.",
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
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True
    assert body["origin"] is None
    assert body["zone"] is None
    assert body["billing_pallets"] is None
    audit_result = client.get(f"/quotes/audit/{body['quote_id']}").json()["result_json"]
    # 120x100x165cm unit is a long piece (>120cm) -> 2 pallets.
    assert audit_result["billing_pallets"] == 2
    assert body["total_price_usd"] is None

    diagnostics = client.get(f"/quotes/hermes-diagnostics?quote_id={body['quote_id']}").json()
    assert len(diagnostics) == 1
    diagnostic = diagnostics[0]
    assert diagnostic["quote_id"] == body["quote_id"]
    assert diagnostic["status"] == "pending"
    assert diagnostic["quote_status"] == "manual_required"

    package = diagnostic["diagnostic_package"]
    assert package["raw_input"] is None
    assert package["address"]["postal_prefix"] == "R3T"
    assert package["address"]["expected_origin_by_province"] == "calgary"
    assert package["zone_hit"]["source_type"] == "manual_required"
    assert package["failure"]["manual_review_required"] is True
    assert package["price_matrix"]["requested_origin"] is None
    assert package["price_matrix"]["requested_zone"] is None
    assert package["price_matrix"]["exact_price_found"] is False
    assert package["neighboring_fsa"][0]["postal_prefix"] == "R3A"
    assert package["neighboring_fsa"][0]["origin"] == "calgary"
    assert package["neighboring_fsa"][0]["zone"] == 5
    assert package["neighboring_fsa"][0]["has_price_for_billing_pallets"] is False
    assert package["neighboring_fsa"][0]["base_price_usd"] is None
    assert "allowed_outputs" in package["agent_contract"]


def test_hermes_diagnostic_suggestion_is_stored_but_does_not_change_quote() -> None:
    client = build_client(
        include_zone_rule=False,
        zone_rule_rows=[
            {
                "postal_prefix": "R3A",
                "city": "WINNIPEG",
                "province": "MB",
                "origin": "calgary",
                "zone": 5,
                "match_level": "legacy",
                "note": "Winnipeg expected-origin anchor",
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
    assert body["source_type"] == "manual_required"
    assert body["manual_review_required"] is True

    diagnostic = client.get(f"/quotes/hermes-diagnostics?quote_id={body['quote_id']}").json()[0]
    rejected = client.post(
        f"/quotes/hermes-diagnostics/{diagnostic['id']}/suggestion",
        json={
            "can_auto_correct": True,
            "reason_zh": "尝试请求自动纠错。",
        },
    )
    assert rejected.status_code == 422

    suggestion = client.post(
        f"/quotes/hermes-diagnostics/{diagnostic['id']}/suggestion",
        json={
            "suggested_action": "suggest_zone_matrix",
            "can_auto_correct": False,
            "confidence": 72,
            "reason_zh": "相邻 R3A 为 Calgary Zone 5，但价格矩阵缺 1 托价格；需人工确认后才能学习。",
            "suggested_origin": "calgary",
            "suggested_zone": 5,
            "missing_table": "zone_price_matrix",
            "recommend_manual_review": True,
            "recommend_learning_candidate": True,
            "evidence_ids": ["zone_rule:R3A"],
        },
    ).json()

    assert suggestion["status"] == "completed"
    assert suggestion["suggested_action"] == "suggest_zone_matrix"
    assert suggestion["confidence"] == 72
    assert suggestion["recommend_manual_review"] is True
    assert suggestion["recommend_learning_candidate"] is True
    assert suggestion["agent_suggestion"]["can_auto_correct"] is False

    audit = client.get(f"/quotes/audit/{body['quote_id']}").json()
    assert audit["source_type"] == "manual_required"
    assert audit["manual_review_required"] is True
    assert audit["total_price_usd"] is None


def test_bound_hermes_model_runs_diagnostic_without_changing_quote(monkeypatch) -> None:
    client = build_client(include_zone_rule=False)
    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    diagnostic = client.get(f"/quotes/hermes-diagnostics?quote_id={quote['quote_id']}").json()[0]
    config = client.post(
        "/ai-configs",
        json={
            "name": "Hermes test model",
            "provider": "openai",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-hermes-test-0001",
            "model_name": "hermes-test",
        },
    ).json()
    client.put("/ai-configs/agents/hermes", json={"config_id": config["id"]})

    monkeypatch.setattr(
        "apps.api.services.hermes_diagnostic_service.OpenAICompatibleClient.complete",
        lambda _client, _messages: AIResponse(
            content=(
                '{"suggested_action":"manual_review","can_auto_correct":false,'
                '"confidence":81,"reason_zh":"证据不足，需人工复核。",'
                '"recommend_manual_review":true,"recommend_learning_candidate":false}'
            )
        ),
    )

    response = client.post(f"/quotes/hermes-diagnostics/{diagnostic['id']}/run")
    audit = client.get(f"/quotes/audit/{quote['quote_id']}").json()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["confidence"] == 81
    assert body["agent_suggestion"]["reason_zh"] == "证据不足，需人工复核。"
    assert audit["source_type"] == "manual_required"
    assert audit["total_price_usd"] is None


def test_bound_hermes_model_repairs_invalid_json_and_drops_unsafe_fields(monkeypatch) -> None:
    client = build_client(include_zone_rule=False)
    quote = client.post("/quotes/zone-calculate", json=payload()).json()
    diagnostic = client.get(f"/quotes/hermes-diagnostics?quote_id={quote['quote_id']}").json()[0]
    config = client.post(
        "/ai-configs",
        json={
            "name": "Hermes repair model",
            "provider": "minimax",
            "base_url": "https://example.invalid/v1",
            "api_key": "sk-hermes-repair-0001",
            "model_name": "MiniMax-M3",
        },
    ).json()
    client.put("/ai-configs/agents/hermes", json={"config_id": config["id"]})

    responses = iter(
        [
            AIResponse(content="<think>unfinished reasoning"),
            AIResponse(
                content=(
                    "已修复：\n```json\n"
                    '{"suggested_action":"manual_review","can_auto_correct":true,'
                    '"confidence":"84%","reason_zh":"证据不足，需人工复核。",'
                    '"recommend_manual_review":"是","recommend_learning_candidate":"否",'
                    '"suggested_price_usd":"999.00",}\n```'
                )
            ),
        ]
    )
    monkeypatch.setattr(
        "apps.api.services.hermes_diagnostic_service.OpenAICompatibleClient.complete",
        lambda _client, _messages: next(responses),
    )

    response = client.post(f"/quotes/hermes-diagnostics/{diagnostic['id']}/run")
    audit = client.get(f"/quotes/audit/{quote['quote_id']}").json()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["confidence"] == 84
    assert body["agent_suggestion"]["can_auto_correct"] is False
    assert "suggested_price_usd" not in body["agent_suggestion"]
    assert audit["source_type"] == "manual_required"
    assert audit["total_price_usd"] is None


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
                "conditions_json": {
                    "address_type": "commercial",
                    "requires_liftgate": False,
                    "requires_pallet_jack": False,
                    "requires_appointment": True,
                    "detention_minutes": 0,
                },
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


def test_zone_switch_blocks_learned_rule_from_reactivating_zone_8() -> None:
    client = build_client(
        learned_rows=[
            {
                "source_task_id": 108,
                "quote_id": "manual-108",
                "scope": "postal_prefix_city",
                "postal_code": "L4K 2N2",
                "postal_prefix": "L4K",
                "city": "CONCORD",
                "province": "ON",
                "origin": "toronto",
                "zone": 8,
                "billing_pallets": 3,
                "conditions_json": {
                    "address_type": "commercial",
                    "requires_liftgate": False,
                    "requires_pallet_jack": False,
                    "requires_appointment": True,
                    "detention_minutes": 0,
                },
                "total_price_usd": Decimal("500.00"),
                "base_price_usd": Decimal("500.00"),
                "confidence": 90,
                "status": "active",
                "usage_count": 0,
                "note": "Legacy approved price that must obey the current zone switch.",
            }
        ]
    )

    response = client.post("/quotes/zone-calculate", json=payload())

    assert response.status_code == 200
    body = response.json()
    assert body["source_type"] == "manual_required"
    assert body["matched_by"] == "zone_price_disabled"
    assert body["match_trace"]["previous_source_type"] == "learned_manual_quote"
    assert body["origin"] == "toronto"
    assert body["zone"] == 8
    assert body["base_price_usd"] is None
    assert body["total_price_usd"] is None
    assert body["manual_review_required"] is True
    assert "zone_price_disabled" in body["risk_tags"]


def test_exact_learned_rule_cannot_cross_origin_price_matrices() -> None:
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
                "origin": "calgary",
                "zone": 5,
                "billing_pallets": 3,
                "conditions_json": {
                    "address_type": "commercial",
                    "requires_liftgate": False,
                    "requires_pallet_jack": False,
                    "requires_appointment": True,
                    "detention_minutes": 0,
                },
                "total_price_usd": Decimal("999.00"),
                "base_price_usd": Decimal("999.00"),
                "confidence": 90,
                "status": "active",
                "usage_count": 0,
                "note": "Wrong-origin learned record must be ignored.",
            }
        ]
    )

    response = client.post("/quotes/zone-calculate", json=payload())

    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["origin"] == "toronto"
    assert body["zone"] == 2
    assert body["total_price_usd"] == "212.00"


def test_exact_learned_rule_does_not_reuse_price_for_different_accessorials() -> None:
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
                "conditions_json": {
                    "address_type": "commercial",
                    "requires_liftgate": False,
                    "requires_pallet_jack": False,
                    "requires_appointment": False,
                    "detention_minutes": 0,
                },
                "total_price_usd": Decimal("250.00"),
                "base_price_usd": Decimal("250.00"),
                "confidence": 72,
                "status": "active",
                "usage_count": 0,
                "note": "Price without appointment service.",
            }
        ]
    )

    response = client.post(
        "/quotes/zone-calculate",
        json=payload(requires_appointment=True),
    )

    body = response.json()
    assert body["source_type"] == "zone_matrix"
    assert body["accessorials"]["appointment_fee_usd"] == "50.00"
    assert body["total_price_usd"] == "212.00"


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
