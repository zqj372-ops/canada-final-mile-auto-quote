from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import APIKey, Base
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.security.api_keys import hash_api_key


def build_customer_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    with session_factory() as session:
        session.add_all([
            APIKey(name="Alice", key_hash=hash_api_key("alice-key"), role="sales", enabled=True),
            APIKey(name="Admin", key_hash=hash_api_key("admin-key"), role="admin", enabled=True),
        ])
        session.commit()

    def override() -> Generator[Session]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override
    return TestClient(app), session_factory


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_customer_api_accepts_only_name_and_returns_paged_public_records() -> None:
    client, _ = build_customer_client()
    created = client.post("/customers", headers={"X-API-Key": "alice-key"}, json={"name": "  Acme  Trading "})
    assert created.status_code == 201
    assert created.json()["name"] == "Acme Trading"

    forbidden = client.post("/customers", headers={"X-API-Key": "alice-key"}, json={"name": "Acme", "email": "leak@example.com"})
    assert forbidden.status_code == 422

    listed = client.get("/customers?limit=10&offset=0", headers={"X-API-Key": "alice-key"})
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["records"][0]["name"] == "Acme Trading"
    assert "email" not in listed.text
