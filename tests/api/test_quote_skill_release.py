"""Regression gates for the personal grants recovered from production."""
from datetime import timedelta

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, SalesQuoteRecord, User
from apps.api.db.session import get_db
from apps.api.routes.quote_skill import router
from apps.api.services.quote_skill_service import (
    authenticate_grant, bind_grant, create_grant, personal_actor, public_grant, utcnow,
)


@pytest.fixture
def fixture_db():
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as db:
        db.add_all([User(username=name, display_name=name, password_hash='fixture-not-a-login', role='sales', enabled=True)
                    for name in ('owner', 'other')])
        db.commit()
        yield db
    engine.dispose()


def test_bind_is_single_use_and_public_response_contains_no_hashes(fixture_db):
    db = fixture_db
    grant, code = create_grant(db, db.get(User, 1), 'fixture')
    assert grant.code_hash != code
    _, _, credential = bind_grant(db, code)
    assert grant.credential_hash != credential
    assert authenticate_grant(db, credential)[1].id == 1
    assert not {'code_hash', 'credential_hash', 'credential', 'authorization_code'} & public_grant(grant).keys()
    with pytest.raises(HTTPException) as error:
        bind_grant(db, code)
    assert error.value.status_code == 401


def test_expired_code_and_revoked_credential_are_rejected(fixture_db):
    db = fixture_db
    grant, code = create_grant(db, db.get(User, 1), 'expired')
    grant.code_expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    with pytest.raises(HTTPException) as error:
        bind_grant(db, code)
    assert error.value.status_code == 401
    grant, code = create_grant(db, db.get(User, 1), 'revoked')
    _, _, credential = bind_grant(db, code)
    grant.enabled = False
    db.commit()
    with pytest.raises(HTTPException) as error:
        authenticate_grant(db, credential)
    assert error.value.status_code == 401


def test_admin_grant_does_not_become_admin_actor(fixture_db):
    user = fixture_db.get(User, 1)
    user.role = 'admin'
    assert personal_actor(user).role == 'sales'


def test_records_cannot_expose_other_owner_or_m2m_scope(fixture_db):
    db = fixture_db
    grant, code = create_grant(db, db.get(User, 1), 'reader')
    _, _, credential = bind_grant(db, code)
    for ident, owner, scope in ((1, 1, 'legacy'), (2, 2, 'legacy'), (3, 1, 'm2m')):
        db.add(SalesQuoteRecord(id=ident, quote_id=f'fixture-{ident}', actor_user_id=owner,
                               actor_name='fixture', actor_role='sales', status='quoted',
                               scope_kind=scope, customer_message='fixture', customer_reply='fixture reply',
                               request_json={}, result_json={'quote_code': str(10_000_000 + ident)}))
    db.commit()
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    assert client.get('/quote-skill/records').status_code == 401
    headers = {'Authorization': 'Bearer ' + credential}
    response = client.get('/quote-skill/records', headers=headers)
    assert response.status_code == 200
    assert [r['quote_code'] for r in response.json()] == ['10000001']
    assert response.headers['cache-control'] == 'no-store'
    for code in ('10000002', '10000003'):
        assert client.get('/quote-skill/records/' + code, headers=headers).status_code == 404
