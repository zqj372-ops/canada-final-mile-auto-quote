"""Exercise actual PostgreSQL row locks in an isolated, disposable CI schema."""
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from apps.api.db.models import Base, HermesLearningCandidate, LearnedQuoteRule
from apps.api.db.repositories.hermes_learning_candidate_repository import HermesLearningCandidateRepository
from tests.services.test_learning_safety import approve, resolve


@pytest.fixture
def pg_engine():
    url = os.getenv('TEST_POSTGRES_URL')
    if not url:
        pytest.skip('TEST_POSTGRES_URL is only set for an isolated test database')
    admin = create_engine(url)
    schema = 'test_learning_' + uuid4().hex
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema} -clock_timeout=5000'})
    try:
        Base.metadata.create_all(engine)
        yield engine
    finally:
        engine.dispose()
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def test_concurrent_resolutions_share_one_candidate_with_two_distinct_cases(pg_engine):
    barrier = Barrier(2)
    def run():
        with Session(pg_engine, expire_on_commit=False) as db:
            barrier.wait(timeout=5)
            return resolve(db).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(run)
        second = pool.submit(run)
        task_ids = {first.result(timeout=10), second.result(timeout=10)}
    with Session(pg_engine) as db:
        candidates = list(db.scalars(select(HermesLearningCandidate)))
        assert len(candidates) == 1
        assert candidates[0].support_count == 2
        assert {case['task_id'] for case in candidates[0].evidence_json['cases']} == task_ids


def test_disabling_rule_locks_candidate_before_rule(pg_engine):
    with Session(pg_engine, expire_on_commit=False) as db:
        resolve(db)
        candidate, rule = approve(db)
        candidate_id, rule_id = candidate.id, rule.id
    started = Event()
    def disable():
        with Session(pg_engine) as db:
            started.set()
            HermesLearningCandidateRepository(db).update_learned_rule_status(rule_id, status='disabled')
    with ThreadPoolExecutor(max_workers=1) as pool:
        with Session(pg_engine) as holding:
            holding.scalar(select(HermesLearningCandidate).where(HermesLearningCandidate.id == candidate_id).with_for_update())
            future = pool.submit(disable)
            assert started.wait(timeout=5)
            # Wait until the competing transaction is blocked on the candidate.
            # If it acquired the rule first, NOWAIT below catches that inversion.
            import time
            deadline = time.monotonic() + 5
            with pg_engine.connect().execution_options(isolation_level='AUTOCOMMIT') as monitor:
                while time.monotonic() < deadline:
                    if monitor.scalar(text("SELECT count(*) FROM pg_stat_activity WHERE wait_event_type = 'Lock' AND query LIKE '%hermes_learning_candidates%'")):
                        break
                    time.sleep(0.02)
                else:
                    pytest.fail('Disabling transaction did not reach candidate lock')
            holding.scalar(select(LearnedQuoteRule).where(LearnedQuoteRule.id == rule_id).with_for_update(nowait=True))
            holding.commit()
        future.result(timeout=10)
    with Session(pg_engine) as db:
        assert db.get(LearnedQuoteRule, rule_id).status == 'disabled'
        assert db.get(HermesLearningCandidate, candidate_id).status == 'pending_review'
