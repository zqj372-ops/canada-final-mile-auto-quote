from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from apps.api.db.models import Base, HermesLearningCandidate, LearnedQuoteRule, ManualQuoteTask
from apps.api.db.repositories.hermes_learning_candidate_repository import HermesLearningCandidateRepository, LearningReviewConflict
from apps.api.db.repositories.learned_quote_rule_repository import LearnedQuoteRuleRepository
from apps.api.services.manual_task_service import ManualQuoteTaskUpdate, update_manual_quote_task
from apps.api.services.quote_service import apply_learned_quote_if_available
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


@pytest.fixture
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    engine.dispose()


def request(**overrides):
    return ZoneQuoteRequest(**{
        "address_line": "100 Fixture Street", "postal_code": "L4K 2N2",
        "city": "Concord", "province": "ON", "cbm": "4.2", "weight_kg": 850,
        "piece_count": 10, "packaging_type": "carton", "address_type": "commercial",
        **overrides,
    })


def result(**overrides):
    return ZoneQuoteResult(**{
        "source_type": "manual_required", "confidence": 0, "postal_code": "L4K 2N2",
        "postal_prefix": "L4K", "city": "CONCORD", "province": "ON", "origin": "toronto",
        "zone": 2, "billing_pallets": 3, "manual_review_required": True,
        "matched_rule": "fixture price gap", **overrides,
    })


def resolve(db, price="100.00", **overrides):
    task = ManualQuoteTask(quote_id=result().quote_id, reason="fixture", risk_tags=[],
                           request_json=request(**overrides).model_dump(mode="json"),
                           result_json=result().model_dump(mode="json"), status="pending")
    db.add(task)
    db.commit()
    update_manual_quote_task(db, task.id, ManualQuoteTaskUpdate(status="resolved", resolved_price_usd=price))
    return task


def approve(db, candidate=None):
    candidate = candidate or db.scalar(select(HermesLearningCandidate))
    now = datetime.now(timezone.utc)
    return HermesLearningCandidateRepository(db).approve(
        candidate.id, reviewed_by="fixture", expected_evidence_version=candidate.proposal_json["evidence_version"],
        price_terms={"supplier": "Fixture Carrier", "source_reference": "Fixture quote 1",
                     "valid_from": now.isoformat(), "valid_until": (now + timedelta(days=7)).isoformat(),
                     "currency": "USD", "price_type": "all_in"},
    )


def test_repeated_edit_is_one_case_and_conflicting_prices_do_not_overwrite(db):
    first = resolve(db)
    update_manual_quote_task(db, first.id, ManualQuoteTaskUpdate(assigned_to="fixture"))
    candidate = db.scalar(select(HermesLearningCandidate))
    assert candidate.support_count == 1
    resolve(db, "300.00")
    assert candidate.support_count == 2
    assert candidate.resolved_total_price_usd == Decimal("100.00")
    assert candidate.proposal_json["price_conflict"] is True
    assert len(candidate.evidence_json["cases"]) == 2
    with pytest.raises(LearningReviewConflict, match="冲突"):
        approve(db)
    assert db.scalar(select(LearnedQuoteRule)) is None


def test_approval_is_atomic_and_idempotent(db, monkeypatch):
    resolve(db)
    candidate = db.scalar(select(HermesLearningCandidate))
    real_commit = db.commit
    monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit unavailable")))
    with pytest.raises(RuntimeError, match="commit unavailable"):
        approve(db)
    assert db.scalar(select(LearnedQuoteRule)) is None
    assert db.get(HermesLearningCandidate, candidate.id).status == "pending_review"
    monkeypatch.setattr(db, "commit", real_commit)
    _, rule = approve(db)
    _, repeated = approve(db)
    assert repeated.id == rule.id
    assert len(db.scalars(select(LearnedQuoteRule)).all()) == 1
    with pytest.raises(LearningReviewConflict, match="禁用"):
        HermesLearningCandidateRepository(db).reject(candidate.id)


@pytest.mark.parametrize("changed", [
    {"address_line": "999 Fixture Street"}, {"postal_code": "L4K 2N3"},
    {"weight_kg": 1000}, {"cbm": "4.3"}, {"piece_count": 11},
    {"packaging_type": "crate"}, {"is_stackable": False}, {"requires_liftgate": True},
])
def test_reuse_requires_same_address_cargo_and_services(db, changed):
    resolve(db)
    approve(db)
    repository = LearnedQuoteRuleRepository(db)
    assert repository.find_best_candidate(request(), result()) is not None
    assert repository.find_best_candidate(request(**changed), result()) is None


def test_expired_and_legacy_rules_fail_closed_and_matrix_remains_authoritative(db):
    resolve(db)
    _, rule = approve(db)
    matrix = result(source_type="zone_matrix", manual_review_required=False, total_price_usd="162.00")
    assert apply_learned_quote_if_available(db, request(), matrix) is matrix
    assert rule.usage_count == 0
    reused = apply_learned_quote_if_available(db, request(), result())
    assert reused.total_price_usd == Decimal("100.00")
    assert reused.base_price_usd is None and reused.fuel_usd is None
    from apps.api.services.quote_logic_explainer import attach_zone_quote_logic
    formula = attach_zone_quote_logic(request(), reused).match_trace["quote_logic"]["price_formula"]
    assert "整口价 USD 100.00" in formula and "未拆分" in formula and "None" not in formula
    rule.conditions_json = {**rule.conditions_json, "price_terms": {
        **rule.conditions_json["price_terms"], "valid_until": "2000-01-01T00:00:00+00:00"}}
    db.commit()
    assert LearnedQuoteRuleRepository(db).find_best_candidate(request(), result()) is None
    rule.conditions_json = {"requires_liftgate": False}
    db.commit()
    assert LearnedQuoteRuleRepository(db).find_best_candidate(request(), result()) is None


def test_manual_price_revision_or_reopen_revokes_published_price(db):
    task = resolve(db)
    candidate, rule = approve(db)
    update_manual_quote_task(db, task.id, ManualQuoteTaskUpdate(resolved_price_usd="200.00", resolved_note="revised fixture"))
    assert candidate.support_count == 1
    assert candidate.status == "pending_review" and rule.status == "disabled"
    assert candidate.evidence_json["revisions"][0]["resolved_price_usd"] == "100.00"
    assert candidate.evidence_json["resolved_price_usd"] == "200.00"
    assert candidate.evidence_json["resolved_note"] == "revised fixture"
    approve(db)
    update_manual_quote_task(db, task.id, ManualQuoteTaskUpdate(status="pending"))
    assert rule.status == "disabled" and candidate.support_count == 0
    with pytest.raises(LearningReviewConflict):
        approve(db)


def test_review_requires_current_evidence_and_price_terms(db):
    resolve(db)
    candidate = db.scalar(select(HermesLearningCandidate))
    repository = HermesLearningCandidateRepository(db)
    with pytest.raises(LearningReviewConflict, match="刷新"):
        repository.approve(candidate.id, expected_evidence_version="stale", price_terms={})
    with pytest.raises(LearningReviewConflict, match="有效"):
        repository.approve(candidate.id, expected_evidence_version=candidate.proposal_json["evidence_version"], price_terms={})


def test_withdrawn_source_requires_review_even_with_another_agreeing_case(db):
    first = resolve(db)
    second = resolve(db)
    candidate, rule = approve(db)
    update_manual_quote_task(db, first.id, ManualQuoteTaskUpdate(status='cancelled'))
    assert candidate.support_count == 1
    assert candidate.source_task_id == second.id
    assert rule.status == 'disabled'
    assert candidate.status == 'pending_review'


def test_manual_task_revision_and_candidate_update_are_atomic(db, monkeypatch):
    from fastapi import HTTPException
    task = resolve(db)
    _, rule = approve(db)
    def fail(*args, **kwargs):
        raise RuntimeError('fixture candidate failure')
    monkeypatch.setattr(HermesLearningCandidateRepository, 'create_from_manual_task', fail)
    with pytest.raises(HTTPException) as exc:
        update_manual_quote_task(db, task.id, ManualQuoteTaskUpdate(resolved_price_usd='200.00'))
    assert exc.value.status_code == 503
    db.refresh(task)
    db.refresh(rule)
    assert task.resolved_price_usd == Decimal('100.00')
    assert rule.status == 'active'


def test_disabled_zone_cannot_increment_rule_usage(db):
    resolve(db)
    _, rule = approve(db)
    original = result(risk_tags=['zone_price_disabled'])
    assert apply_learned_quote_if_available(db, request(), original) is original
    assert rule.usage_count == 0


def test_neighbor_diagnostics_use_two_queries_for_eighteen_rules(db):
    from sqlalchemy import event
    from apps.api.db.models import ZoneLookupRule, ZonePriceMatrix
    from apps.api.db.repositories.zone_repository import ZoneRepository
    from apps.api.services.hermes_diagnostic_service import _neighboring_fsa_context
    for i in range(60):
        db.add(ZoneLookupRule(postal_prefix='L4K', city=f'CITY {i}', province='ON', origin='toronto', zone=2))
    db.add(ZonePriceMatrix(origin='toronto', zone=2, billing_pallets=3, base_price_usd=100, source='fixture'))
    db.commit()
    statements = []
    def count(connection, cursor, statement, *args):
        statements.append(statement)
    event.listen(db.bind, 'before_cursor_execute', count)
    try:
        rows = _neighboring_fsa_context(ZoneRepository(db), 'L4K', 'ON', 3)
    finally:
        event.remove(db.bind, 'before_cursor_execute', count)
    assert len(rows) == 18
    assert all(row['base_price_usd'] == '100.00' for row in rows)
    assert len(statements) == 2


def test_relevant_history_is_filtered_before_global_recency_limit(db):
    from apps.api.services.hermes_diagnostic_service import _historical_manual_confirmations
    first = resolve(db)
    for i in range(200):
        db.add(ManualQuoteTask(quote_id=f'unrelated-{i}', reason='fixture', risk_tags=[], status='resolved',
                              resolved_price_usd=50, request_json={'city': 'Vancouver', 'province': 'BC'},
                              result_json={'billing_pallets': 3}))
    db.commit()
    rows = _historical_manual_confirmations(db, city='Concord', province='ON', postal_prefix='L4K', billing_pallets=3)
    assert [row['manual_task_id'] for row in rows] == [first.id]


def test_m2m_records_are_excluded_from_workbench_and_learning(db):
    from fastapi import HTTPException
    from apps.api.auth import CurrentActor
    from apps.api.db.models import SalesQuoteRecord
    from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
    from apps.api.db.repositories.sales_quote_record_repository import SalesQuoteRecordRepository
    from apps.api.services.audit_service import get_quote_error_summary
    from apps.api.services.hermes_diagnostic_service import _historical_manual_confirmations
    from apps.api.services.quote_workbench_service import _lock_superseded_task

    task = ManualQuoteTask(quote_id='m2m-fixture', scope_kind='m2m', learning_eligible=False,
        reason='fixture', risk_tags=[], status='resolved', resolved_price_usd=100,
        request_json=request().model_dump(mode='json'), result_json=result().model_dump(mode='json'))
    record = SalesQuoteRecord(quote_id=task.quote_id, scope_kind='m2m', status='manual_required',
        customer_message='fixture', request_json={}, result_json={})
    db.add_all([task, record])
    db.commit()
    task_repo = ManualQuoteTaskRepository(db)
    sales_repo = SalesQuoteRecordRepository(db)
    actor = CurrentActor(name='fixture admin', role='admin', api_key_id=None)
    assert task_repo.list_tasks() == [] and task_repo.get(task.id) is None
    assert sales_repo.list_records(actor=actor) == []
    assert sales_repo.get_record(record.id) is None
    assert sales_repo.get_latest_record_by_quote_id(task.quote_id) is None
    assert HermesLearningCandidateRepository(db).create_from_manual_task(task) is None
    assert _historical_manual_confirmations(db, city='Concord', province='ON', postal_prefix='L4K', billing_pallets=3) == []
    summary = get_quote_error_summary(db)
    assert summary['recent_manual_tasks'] == [] and summary['resolved_manual_task_count'] == 0
    with pytest.raises(HTTPException) as failure:
        update_manual_quote_task(db, task.id, ManualQuoteTaskUpdate(status='cancelled'))
    assert failure.value.status_code == 404
    with pytest.raises(HTTPException) as failure:
        _lock_superseded_task(db, task.quote_id, actor)
    assert failure.value.status_code == 409
    db.refresh(task)
    assert task.status == 'resolved'


def test_learning_opt_out_is_respected_even_for_legacy_task(db):
    from apps.api.services.hermes_diagnostic_service import _historical_manual_confirmations
    task = ManualQuoteTask(quote_id='opt-out-fixture', scope_kind='legacy', learning_eligible=False,
        reason='fixture', risk_tags=[], status='resolved', resolved_price_usd=100,
        request_json=request().model_dump(mode='json'), result_json=result().model_dump(mode='json'))
    db.add(task)
    db.commit()
    assert HermesLearningCandidateRepository(db).create_from_manual_task(task) is None
    assert _historical_manual_confirmations(db, city='Concord', province='ON', postal_prefix='L4K', billing_pallets=3) == []
