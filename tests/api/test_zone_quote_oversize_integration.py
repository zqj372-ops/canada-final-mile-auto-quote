from __future__ import annotations

import json
from collections.abc import Generator
from contextlib import contextmanager
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import (
    AIModelConfig,
    Base,
    LearnedQuoteRule,
    ManualQuoteTask,
    OversizePalletRuleVersion,
    PostalCodeCityLookup,
    QuoteRuleConfig,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.services.quote_service import _result_from_learned_rule
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft, ExtractedCargoItem
from packages.quote_engine.oversize_config import default_oversize_pallet_rule
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult, ZoneQuoteSourceType


@pytest.fixture()
def client() -> Generator[TestClient, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        session.add(
            ZoneLookupRule(
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                match_level="test",
            )
        )
        session.add_all(
            [
                ZonePriceMatrix(origin="toronto", zone=2, billing_pallets=1, base_price_usd=Decimal("101.00")),
                ZonePriceMatrix(origin="toronto", zone=2, billing_pallets=2, base_price_usd=Decimal("202.00")),
                ZonePriceMatrix(origin="toronto", zone=2, billing_pallets=3, base_price_usd=Decimal("303.00")),
            ]
        )
        session.commit()

    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _request_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "address_line": "8888 Keele St",
        "postal_code": "L4K 2N2",
        "city": "Concord",
        "province": "ON",
        "cbm": "1.00",
        "weight_kg": "900",
        "piece_count": 1,
        "packaging_type": "carton",
        "longest_side_cm": "100",
        "address_type": "commercial",
        "handling_units": [
            {
                "quantity": 1,
                "packaging_type": "carton",
                "length_cm": "100",
                "width_cm": "100",
                "height_cm": "100",
                "unit_weight_kg": "900",
            }
        ],
    }
    payload.update(overrides)
    return payload


def _published_and_draft_rules(client: TestClient) -> tuple[dict[str, object], dict[str, object]]:
    # The fixture's database is held by the dependency override closure.  Use
    # the app override directly so the test only exercises the API boundary.
    override = app.dependency_overrides[get_db]
    generator = override()
    session = next(generator)
    try:
        published = default_oversize_pallet_rule().model_copy(
            update={"weight_kg_per_pallet": Decimal("1000")}
        )
        draft = default_oversize_pallet_rule().model_copy(
            update={"weight_kg_per_pallet": Decimal("400")}
        )
        session.add(
            QuoteRuleConfig(
                key="oversize_pallet_rule_draft",
                value=json.dumps(draft.model_dump(mode="json")),
                description="test draft only",
            )
        )
        session.add(
            OversizePalletRuleVersion(
                rule_id=published.rule_id,
                version=7,
                config_json=published.model_dump(mode="json"),
                published_by="test",
                status="published",
            )
        )
        session.commit()
        return published.model_dump(mode="json"), draft.model_dump(mode="json")
    finally:
        generator.close()


def test_zone_uses_published_rule_not_draft_and_audits_full_snapshot(client: TestClient) -> None:
    published, draft = _published_and_draft_rules(client)

    response = client.post("/quotes/zone-calculate", json=_request_payload())
    assert response.status_code == 200
    public = response.json()
    assert public["billing_pallets"] == 1
    assert set(public) == {
        "quote_id",
        "billing_pallets",
        "total_price_usd",
        "sales_note",
        "manual_review_required",
        "public_flags",
    }

    audit = client.get(f"/quotes/audit/{public['quote_id']}").json()
    result = audit["result_json"]
    trace = result["internal_trace"]
    assert result["billing_pallets"] == 1
    assert trace["rule_id"] == published["rule_id"]
    assert trace["rule_version"] == 7
    assert trace["rule_snapshot"] == published
    assert trace["rule_snapshot"] != draft
    assert trace["handling_units"][0]["length_cm"] == "100"
    assert trace["calculator"]["totals"]["weight_pallets"] == 1
    assert trace["vehicle"]["status"] == "reference_only"


def test_invalid_published_rule_fails_closed_without_default_fallback(client: TestClient) -> None:
    with _db_session_from_client() as session:
        session.add(
            OversizePalletRuleVersion(
                rule_id="BROKEN_PUBLISHED_RULE",
                version=9,
                config_json={"rule_id": "", "volume_cbm_per_pallet": 0},
                published_by="test",
                status="published",
            )
        )
        session.commit()

    response = client.post("/quotes/zone-calculate", json=_request_payload())

    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is True
    assert public["billing_pallets"] is None
    audit = client.get(f"/quotes/audit/{public['quote_id']}").json()
    result = audit["result_json"]
    assert "oversize_rule_invalid" in result["risk_tags"]
    assert result["internal_trace"]["rule_version"] == 9
    assert result["internal_trace"]["rule_snapshot"] == {
        "rule_id": "BROKEN_PUBLISHED_RULE",
        "invalid_reason": "published_snapshot_invalid",
    }


def test_zone_and_ai_services_share_published_snapshot_and_ai_public_allowlist(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    published, _draft = _published_and_draft_rules(client)
    with _db_session_from_client() as session:
        session.add(
            AIModelConfig(
                name="integration-ai",
                provider="openai",
                base_url="https://example.invalid/v1",
                api_key_encrypted="xor1:AA==",
                model_name="test",
                is_default=True,
                enabled=True,
            )
        )
        session.commit()

    extraction = AIExtractedQuoteDraft(
        address_line="8888 Keele St",
        postal_code="L4K 2N2",
        city="Concord",
        province="ON",
        cbm=Decimal("1"),
        weight_kg=Decimal("900"),
        piece_count=1,
        packaging_type="carton",
        longest_side_cm=Decimal("100"),
        address_type="commercial",
        missing_fields=[],
        cargo_items=[
            ExtractedCargoItem(
                quantity=1,
                length_cm=Decimal("100"),
                width_cm=Decimal("100"),
                height_cm=Decimal("100"),
                weight_kg=Decimal("900"),
            )
        ],
    )
    monkeypatch.setattr("apps.api.services.ai_quote_service.extract_quote_draft", lambda *_args: extraction)
    monkeypatch.setattr(
        "apps.api.services.ai_quote_service._build_guarded_sales_note",
        lambda _client, quote_result: quote_result.sales_note,
    )
    monkeypatch.setattr(
        "apps.api.services.ai_quote_service._zone_request_from_extraction",
        lambda _extraction: ZoneQuoteRequest(**_request_payload()),
    )

    response = client.post("/quotes/ai-auto-quote", json={"customer_message": "quote this"})
    assert response.status_code == 200
    body = response.json()
    assert body["quote_result"]["billing_pallets"] == 1
    assert set(body["quote_result"]) == {
        "quote_id",
        "billing_pallets",
        "total_price_usd",
        "sales_note",
        "manual_review_required",
        "public_flags",
    }

    # The AI path writes a SalesQuoteRecord, while its deterministic internal
    # result is still available through the quote audit created by side effects.
    quote_id = body["quote_result"]["quote_id"]
    audit = client.get(f"/quotes/audit/{quote_id}").json()
    trace = audit["result_json"]["internal_trace"]
    assert trace["rule_id"] == published["rule_id"]
    assert trace["rule_version"] == 7
    assert trace["rule_snapshot"] == published


def test_oversize_manual_keeps_candidate_internal_but_blocks_learning_and_reuse(client: TestClient) -> None:
    _published_and_draft_rules(client)
    with _db_session_from_client() as session:
        session.add(
            LearnedQuoteRule(
                source_task_id=900,
                quote_id="old-quote",
                scope="postal_prefix_city",
                postal_code="L4K 2N2",
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                billing_pallets=3,
                conditions_json={
                    "address_type": "commercial",
                    "requires_liftgate": False,
                    "requires_pallet_jack": False,
                    "requires_appointment": False,
                    "detention_minutes": 0,
                },
                total_price_usd=Decimal("999"),
                base_price_usd=Decimal("999"),
                confidence=99,
                status="active",
            )
        )
        session.commit()

    response = client.post(
        "/quotes/zone-calculate",
        json=_request_payload(
            weight_kg="1000.01",
            handling_units=[
                {
                    "quantity": 1,
                    "packaging_type": "crate",
                    "length_cm": "200",
                    "width_cm": "130",
                    "height_cm": "100",
                    "unit_weight_kg": "1000.01",
                }
            ],
            cbm="2.60",
            packaging_type="crate",
            longest_side_cm="200",
        ),
    )
    assert response.status_code == 200
    public = response.json()
    assert public["manual_review_required"] is True
    assert public["billing_pallets"] is None

    quote_id = public["quote_id"]
    audit = client.get(f"/quotes/audit/{quote_id}").json()
    result = audit["result_json"]
    assert result["billing_pallets"] == 3
    assert "unit_weight_over_mechanical_limit" in result["risk_tags"]
    assert "oversize_rule_id" in result["internal_trace"]

    tasks = client.get("/quotes/manual-tasks").json()
    assert len(tasks) == 1
    assert tasks[0]["result_json"]["billing_pallets"] == 3
    assert "unit_weight_over_mechanical_limit" in tasks[0]["risk_tags"]

    resolved = client.patch(
        f"/quotes/manual-tasks/{tasks[0]['id']}",
        json={"status": "resolved", "resolved_price_usd": "450.00"},
    )
    assert resolved.status_code == 200
    candidates = client.get("/quotes/learning-candidates").json()
    assert candidates == []


def test_learned_reuse_preserves_oversize_audit_trace() -> None:
    request = ZoneQuoteRequest(**_request_payload())
    original = ZoneQuoteResult(
        source_type=ZoneQuoteSourceType.MANUAL_REQUIRED,
        confidence=0,
        postal_code="L4K 2N2",
        postal_prefix="L4K",
        city="CONCORD",
        province="ON",
        origin="toronto",
        zone=2,
        billing_pallets=3,
        pallet_breakdown={"size_pallets": 3},
        risk_tags=["zone_price_not_found"],
        manual_review_required=True,
        matched_rule="manual oversize review",
        match_trace={"matched_by": "zone_matrix"},
        internal_trace={"calculator": {"totals": {"size_pallets": 3}}, "vehicle": {"status": "FIT"}},
        oversize_rule_id="NA_OVERSIZE_TEMP_V1",
        oversize_rule_version="7",
        oversize_rule_snapshot={"rule_id": "NA_OVERSIZE_TEMP_V1", "weight_basis_kg": "1000"},
        oversize_accessorials={"heavy": Decimal("75")},
    )
    rule = LearnedQuoteRule(
        source_task_id=901,
        scope="postal_prefix",
        postal_prefix="L4K",
        billing_pallets=3,
        total_price_usd=Decimal("999"),
        base_price_usd=Decimal("999"),
        confidence=99,
    )

    reused = _result_from_learned_rule(request, original, rule, match_score=100)

    assert reused.internal_trace["calculator"] == original.internal_trace["calculator"]
    assert reused.internal_trace["vehicle"] == original.internal_trace["vehicle"]
    assert reused.internal_trace["learned_reuse"]["source_task_id"] == 901
    assert reused.match_trace == original.match_trace
    assert reused.oversize_rule_id == original.oversize_rule_id
    assert reused.oversize_rule_version == original.oversize_rule_version
    assert reused.oversize_rule_snapshot == original.oversize_rule_snapshot
    assert reused.oversize_accessorials == original.oversize_accessorials


@contextmanager
def _db_session_from_client() -> Generator[Session, None, None]:
    override = app.dependency_overrides[get_db]
    generator = override()
    try:
        yield next(generator)
    finally:
        generator.close()
