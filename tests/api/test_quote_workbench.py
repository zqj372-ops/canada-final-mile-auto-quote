from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, ZoneLookupRule, ZonePriceMatrix, PostalCodeCityLookup, QuoteAuditLog, ManualQuoteTask, SalesQuoteRecord, HermesDiagnosticQueue
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.services.quote_workbench_service import ConfirmedQuote

SAMPLE = """数量: 2托盘
尺寸: 120x100x150 cm
总重: 800 kg
地址: 8888 Keele St
城市: Concord
省份: ON
邮编: L4K 2N2
地址类型: 商业地址
尾板: 否"""


@pytest.fixture
def context():
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        db.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        db.add(ZoneLookupRule(postal_prefix="L4K", city="CONCORD", province="ON", origin="toronto", zone=2, match_level="test", note=""))
        db.add(ZonePriceMatrix(origin="toronto", zone=2, billing_pallets=3, base_price_usd=Decimal("120"), source="test", last_updated="2026-10-12"))
        db.commit()
    def session():
        with factory() as db:
            yield db
    app.dependency_overrides[get_db] = session
    with TestClient(app) as client:
        yield client, factory
    app.dependency_overrides.clear()
    engine.dispose()


def payload(**changes):
    services = {"requires_liftgate": False, "requires_pallet_jack": False, "requires_appointment": False}
    services.update(changes)
    quote = ConfirmedQuote(address_line="8888 Keele St", postal_code="L4K 2N2", city="Concord", province="ON",
                           cbm="4.2", weight_kg=850, piece_count=10, packaging_type="carton", address_type="commercial", **services)
    return {"customer_message": "原文包含旧字段；以确认字段为准", "quote": quote.model_dump(mode="json"),
            "field_provenance": {k: "human_edited" for k, v in quote.model_dump().items() if v is not None}}


def counts(factory):
    with factory() as db:
        return [db.scalar(select(func.count()).select_from(model)) for model in (QuoteAuditLog, ManualQuoteTask, SalesQuoteRecord, HermesDiagnosticQueue)]


def test_local_extraction_needs_no_model_and_has_no_side_effects(context, monkeypatch):
    client, factory = context
    def forbidden(*args, **kwargs):
        raise AssertionError("No model, quote or notification should run during local extraction")
    monkeypatch.setattr("apps.api.services.quote_workbench_service.OpenAICompatibleClient", forbidden)
    monkeypatch.setattr("apps.api.services.quote_workbench_service.ZoneQuoteEngine.quote", forbidden)
    response = client.post("/quotes/ai-extract", json={"customer_message": SAMPLE})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extraction_mode"] == "local"
    assert body["extraction"]["weight_kg"] == "800.0"
    assert {item["field"] for item in body["draft_validation_errors"]} == {"requires_pallet_jack", "requires_appointment"}
    assert "quote_result" not in body
    assert body["field_provenance"]["requires_liftgate"] == "deterministic_extracted"
    assert body["field_provenance"]["detention_minutes"] == "deterministic_extracted"
    assert counts(factory) == [0, 0, 0, 0]


def test_force_model_without_config_returns_error_without_creating_tasks(context):
    client, factory = context
    response = client.post("/quotes/ai-extract", json={"customer_message": SAMPLE, "force_ai": True})
    assert response.status_code == 400
    assert counts(factory) == [0, 0, 0, 0]


def test_confirmed_quote_uses_confirmed_input_and_saves_real_records(context, monkeypatch):
    client, factory = context
    monkeypatch.setattr("apps.api.services.quote_workbench_service.extract_quote_draft_with_agents", lambda *a, **k: pytest.fail("AI must not run"))
    monkeypatch.setattr("apps.api.services.quote_workbench_service.apply_learned_quote_if_available", lambda *a, **k: pytest.fail("Matrix price must remain authoritative"))
    response = client.post("/quotes/confirmed-calculate", json=payload())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["quote_result"]["source_type"] == "zone_matrix"
    assert body["quote_result"]["base_price_usd"] == "120.00"
    assert body["sales_record_id"] > 0 and body["manual_task_id"] is None
    assert counts(factory) == [1, 0, 1, 1]
    with factory() as db:
        record = db.get(SalesQuoteRecord, body["sales_record_id"])
        assert record.status == "quoted"
        assert record.request_json["quote"]["weight_kg"] == "850"


@pytest.fixture
def york_context(context):
    client, factory = context
    with factory() as db:
        db.add(PostalCodeCityLookup(postal_code="M6B 3P8", preferred_city="York", province="ON"))
        # Deliberately distinct fixture zones prove that postal city wins.
        for city, zone in (("YORK", 2), ("TORONTO", 4)):
            db.add(ZoneLookupRule(postal_prefix="M6B", city=city, province="ON", origin="toronto", zone=zone, note="Fixture only"))
        db.commit()
    return client, factory


def test_city_mismatch_is_advisory_during_extraction(york_context):
    client, factory = york_context
    message = SAMPLE.replace("8888 Keele St", "2464 Dufferin St, Toronto, Ontario, Canada, M6B 3P8")
    message = message.replace("Concord", "Toronto").replace("L4K 2N2", "M6B 3P8")
    message += "\n手叉车: 否\n预约: 否"
    response = client.post("/quotes/ai-extract", json={"customer_message": message})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["extraction"]["city"] == "Toronto"
    assert body["extraction"]["postal_code"] == "M6B 3P8"
    assert body["address_validation"]["city_consistent"] is False
    assert body["address_validation"]["preferred_city"] == "York"
    assert "不阻止报价" in body["address_validation"]["note_zh"]
    assert body["draft_validation_errors"] == []
    assert counts(factory) == [0, 0, 0, 0]


def test_confirmed_quote_prefers_postal_city_and_preserves_input(york_context):
    client, factory = york_context
    body = payload()
    body["quote"].update(address_line="2464 Dufferin St, Toronto, Ontario, Canada, M6B 3P8",
                         postal_code="M6B 3P8", city="Toronto", province="Ontario")
    response = client.post("/quotes/confirmed-calculate", json=body)
    assert response.status_code == 200, response.text
    saved = response.json()
    result = saved["quote_result"]
    assert result["source_type"] == "zone_matrix"
    assert result["postal_code"] == "M6B 3P8"
    assert result["city"] == result["preferred_city"] == "York"
    assert result["province"] == "ON"
    assert result["zone"] == 2
    assert result["base_price_usd"] == "120.00"
    assert result["manual_review_required"] is False
    assert result["match_trace"]["input_city"] == "Toronto"
    assert result["match_trace"]["city_match_source"] == "postal_lookup"
    assert counts(factory) == [1, 0, 1, 1]
    with factory() as db:
        record = db.get(SalesQuoteRecord, saved["sales_record_id"])
        assert record.request_json["quote"]["city"] == "Toronto"
        assert record.request_json["quote"]["address_line"] == body["quote"]["address_line"]
        audit = db.scalar(select(QuoteAuditLog).where(QuoteAuditLog.quote_id == result["quote_id"]))
        assert audit.request_json["city"] == "Toronto"


def test_postal_city_with_conflicting_rules_still_requires_manual_review(york_context):
    client, factory = york_context
    with factory() as db:
        db.add(ZoneLookupRule(postal_prefix="M6B", city="YORK", province="ON", origin="toronto", zone=3, note="Conflicting fixture"))
        db.commit()
    body = payload()
    body["quote"].update(address_line="2464 Dufferin St", postal_code="M6B 3P8", city="Toronto")
    response = client.post("/quotes/confirmed-calculate", json=body)
    assert response.status_code == 200, response.text
    result = response.json()["quote_result"]
    assert result["manual_review_required"] is True
    assert result["matched_by"] == "split_record_conflict"
    assert result["total_price_usd"] is None
    assert response.json()["manual_task_id"] is not None


@pytest.mark.parametrize("mutation", ["missing_provenance", "result_field", "source_value", "wrong_province", "empty_city", "soft_packaging", "invalid_postal"])
def test_invalid_confirmed_fields_do_not_write(context, mutation):
    client, factory = context
    body = payload()
    if mutation == "missing_provenance": del body["field_provenance"]["requires_liftgate"]
    if mutation == "result_field": body["field_provenance"]["total_price_usd"] = "human_edited"
    if mutation == "source_value": body["field_provenance"]["city"] = "system_derived"
    if mutation == "wrong_province": body["quote"]["province"] = "BC"
    if mutation == "empty_city": body["quote"]["city"] = ""
    if mutation == "soft_packaging": body["quote"]["packaging_type"] = "woven_bag"
    if mutation == "invalid_postal": body["quote"]["postal_code"] = "L4D 2N2"
    response = client.post("/quotes/confirmed-calculate", json=body)
    assert response.status_code == 422
    assert counts(factory) == [0, 0, 0, 0]


def test_atomic_rollback_if_sales_record_cannot_be_saved(context, monkeypatch):
    client, factory = context
    def fail(*a, **k): raise RuntimeError("fixture write failure")
    monkeypatch.setattr("apps.api.services.quote_workbench_service.SalesQuoteRecordRepository.create_record", fail)
    body = payload(); body["quote"]["cbm"] = "30"
    response = client.post("/quotes/confirmed-calculate", json=body)
    assert response.status_code == 503
    assert "quote_result" not in response.json()
    assert counts(factory) == [0, 0, 0, 0]


def test_manual_task_replaced_once_in_same_transaction_without_notifications(context, monkeypatch):
    client, factory = context
    def forbidden(*a, **k): pytest.fail("Confirmed workflow must not send notifications")
    monkeypatch.setattr("apps.api.services.quote_service.notify_manual_required", forbidden)
    first = payload(); first["quote"]["cbm"] = "30"
    original = client.post("/quotes/confirmed-calculate", json=first)
    assert original.status_code == 200, original.text
    old = original.json()
    assert old["manual_task_id"] is not None
    body = payload(); body["supersedes_quote_id"] = old["quote_result"]["quote_id"]
    replacement = client.post("/quotes/confirmed-calculate", json=body)
    assert replacement.status_code == 200, replacement.text
    assert replacement.json()["superseded_task_id"] == old["manual_task_id"]
    assert client.post("/quotes/confirmed-calculate", json=body).status_code == 409
    with factory() as db:
        assert db.get(ManualQuoteTask, old["manual_task_id"]).status == "cancelled"
        assert db.get(SalesQuoteRecord, old["sales_record_id"]).status == "superseded"
    assert len(client.get("/quotes/sales-records?status=superseded").json()) == 1


def test_failed_replacement_restores_original_pending_task(context, monkeypatch):
    client, factory = context
    first = payload(); first["quote"]["cbm"] = "30"
    old = client.post("/quotes/confirmed-calculate", json=first).json()
    before = counts(factory)
    def fail(*a, **k): raise RuntimeError("fixture save failure")
    monkeypatch.setattr("apps.api.services.quote_workbench_service.SalesQuoteRecordRepository.create_record", fail)
    replacement = payload(); replacement["supersedes_quote_id"] = old["quote_result"]["quote_id"]
    assert client.post("/quotes/confirmed-calculate", json=replacement).status_code == 503
    assert counts(factory) == before
    with factory() as db:
        assert db.get(ManualQuoteTask, old["manual_task_id"]).status == "pending"
        assert db.get(SalesQuoteRecord, old["sales_record_id"]).status == "manual_required"


def test_diagnostic_outbox_failure_rolls_back_quote_atomically(context, monkeypatch):
    client, factory = context
    def fail(*a, **k): raise RuntimeError("fixture diagnostic failure")
    monkeypatch.setattr("apps.api.services.quote_workbench_service.enqueue_quote_diagnostic", fail)
    response = client.post("/quotes/confirmed-calculate", json=payload())
    assert response.status_code == 503
    assert counts(factory) == [0, 0, 0, 0]


def test_customer_reply_matches_selected_services_and_current_fee_config(context):
    from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
    from packages.quote_engine.zone_config import ZonePricingConfig
    client, factory = context
    with factory() as db:
        QuoteRuleConfigRepository(db).save_zone_pricing_config(ZonePricingConfig(
            liftgate_fee_usd=70, pallet_jack_fee_usd=65, detention_free_minutes=45, detention_half_hour_fee_usd=40))
    response = client.post("/quotes/confirmed-calculate", json=payload(requires_liftgate=True, requires_pallet_jack=True, requires_appointment=True, detention_minutes=60))
    assert response.status_code == 200, response.text
    note = response.json()["quote_result"]["sales_note"]
    assert "不带尾板" not in note and "需手叉车配合 +" not in note
    assert "已含尾板费 USD 70" in note
    assert "已含手叉车费 USD 65" in note
    assert "已含预约费 USD 50" in note
    assert "已含等待费 USD 40" in note
    assert "免费等待45分钟，超时40USD/半小时" in note
    response = client.post("/quotes/confirmed-calculate", json=payload())
    note = response.json()["quote_result"]["sales_note"]
    assert "需尾板 +70USD/票" in note and "需手叉车配合 +65USD/票" in note


def test_permissions_and_supersession_ownership(context, monkeypatch):
    from apps.api.db.repositories.api_key_repository import APIKeyRepository
    client, factory = context
    monkeypatch.setenv("DEV_AUTH_DISABLED", "false")
    with factory() as db:
        repo = APIKeyRepository(db)
        _, sales_key = repo.create_key(name="fixture-sales", role="sales")
        _, other_key = repo.create_key(name="fixture-other", role="sales")
        _, viewer_key = repo.create_key(name="fixture-viewer", role="viewer")
    for path, body in [("/quotes/ai-extract", {"customer_message": SAMPLE}), ("/quotes/confirmed-calculate", payload())]:
        assert client.post(path, json=body).status_code == 401
        assert client.post(path, json=body, headers={"X-API-Key": viewer_key}).status_code == 403
    first = payload(); first["quote"]["cbm"] = "30"
    response = client.post("/quotes/confirmed-calculate", json=first, headers={"X-API-Key": sales_key})
    assert response.status_code == 200
    old = response.json()
    replacement = payload(); replacement["supersedes_quote_id"] = old["quote_result"]["quote_id"]
    assert client.post("/quotes/confirmed-calculate", json=replacement, headers={"X-API-Key": other_key}).status_code == 409
    assert client.post("/quotes/confirmed-calculate", json=replacement, headers={"X-API-Key": sales_key}).status_code == 200


def test_background_context_failure_preserves_saved_quote(context, monkeypatch):
    from apps.api.services.hermes_diagnostic_service import prepare_hermes_context
    client, factory = context
    response = client.post("/quotes/confirmed-calculate", json=payload())
    assert response.status_code == 200
    def fail(*a, **k):
        raise RuntimeError("fixture context failure")
    monkeypatch.setattr("apps.api.services.hermes_diagnostic_service.build_quote_diagnostic_package", fail)
    with factory() as db:
        prepared = prepare_hermes_context(db)
        assert prepared["diagnostic_package"]["context_status"] == "failed"
    assert counts(factory) == [1, 0, 1, 1]


def extraction_confirmation(client):
    extraction = client.post('/quotes/ai-extract', json={'customer_message': SAMPLE}).json()
    quote = {key: extraction['extraction'][key] for key in ConfirmedQuote.model_fields}
    for key in ('requires_liftgate', 'requires_pallet_jack', 'requires_appointment'):
        quote[key] = quote[key] if quote[key] is not None else False
    quote['cbm'] = '4.0'
    return {'customer_message': SAMPLE, 'quote': quote,
            'field_provenance': {key: 'human_edited' for key, value in quote.items() if value is not None},
            'extraction_snapshot': extraction['extraction'], 'extraction_receipt': extraction['extraction_receipt'],
            'correction_reasons': {'cbm': 'extraction_error', 'requires_pallet_jack': 'business_decision'}}


def test_verified_corrections_require_review_and_do_not_train_on_business_changes(context):
    client, factory = context
    data = extraction_confirmation(client)
    response = client.post('/quotes/confirmed-calculate', json=data)
    assert response.status_code == 200, response.text
    quote_id = response.json()['quote_result']['quote_id']
    audit = client.get(f'/quotes/audit/{quote_id}').json()
    feedback = audit['request_json']['extraction_feedback']
    assert feedback['verified_source'] is True
    assert feedback['status'] == 'pending_review'
    assert feedback['metadata']['model_calls'] == 0
    review = {'expected_version': feedback['version'], 'approved_fields': ['requires_pallet_jack'],
              'note': 'Fixture reviewer checked source', 'evaluation_group': 'fixture-template-1'}
    assert client.patch(f'/quotes/audit/{quote_id}/extraction-feedback', json=review).status_code == 422
    review['approved_fields'] = ['cbm']
    reviewed = client.patch(f'/quotes/audit/{quote_id}/extraction-feedback', json=review)
    assert reviewed.status_code == 200
    assert reviewed.json()['approved_fields'] == ['cbm']
    assert reviewed.json()['split'] == 'test'
    from scripts.export_extraction_feedback import reviewed_cases
    with factory() as db:
        exported = list(reviewed_cases(db))
    assert len(exported) == 1
    assert exported[0]['expected_fields'] == {'cbm': '4.0'}
    assert exported[0]['source'] == 'operator_reviewed'

    assert client.patch(f'/quotes/audit/{quote_id}/extraction-feedback', json=review).status_code == 409
    assert counts(factory) == [1, 1, 1, 1]


def test_tampered_extraction_cannot_be_saved_as_verified_feedback(context):
    client, factory = context
    data = extraction_confirmation(client)
    data['extraction_snapshot']['weight_kg'] = '99999'
    assert client.post('/quotes/confirmed-calculate', json=data).status_code == 422
    assert counts(factory) == [0, 0, 0, 0]


def test_unverified_snapshot_is_reference_only(context):
    client, factory = context
    data = extraction_confirmation(client)
    data.pop('extraction_receipt')
    response = client.post('/quotes/confirmed-calculate', json=data)
    quote_id = response.json()['quote_result']['quote_id']
    audit = client.get(f'/quotes/audit/{quote_id}').json()
    feedback = audit['request_json']['extraction_feedback']
    assert feedback['verified_source'] is False
    review = {'expected_version': feedback['version'], 'approved_fields': ['cbm'],
              'note': 'Cannot approve unverified fixture', 'evaluation_group': 'fixture'}
    assert client.patch(f'/quotes/audit/{quote_id}/extraction-feedback', json=review).status_code == 422


def test_confirmed_calculate_requires_explicit_service_choices(context):
    client, factory = context
    data = payload()
    data['quote'].pop('requires_liftgate')
    assert client.post('/quotes/confirmed-calculate', json=data).status_code == 422
    assert counts(factory) == [0, 0, 0, 0]


def test_quote_enqueue_does_not_collect_expensive_context(context, monkeypatch):
    client, factory = context
    def forbidden(*a, **k):
        raise AssertionError("Expensive context must be deferred")
    for name in ('_private_reference_context', '_historical_manual_confirmations', '_neighboring_fsa_context', '_price_matrix_context'):
        monkeypatch.setattr('apps.api.services.hermes_diagnostic_service.' + name, forbidden)
    response = client.post('/quotes/confirmed-calculate', json=payload())
    assert response.status_code == 200
    with factory() as db:
        queued = db.scalar(select(HermesDiagnosticQueue))
        assert queued.diagnostic_package_json['context_status'] == 'pending'
