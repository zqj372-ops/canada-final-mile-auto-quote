from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, PostalCodeCityLookup
from apps.api.db.session import get_db
from apps.api.main import app


def test_maps_embed_redirects_to_google_embed_url() -> None:
    client = TestClient(app)

    response = client.get(
        "/maps/embed",
        params={"query": "440  Hodgson Blvd NW   Edmonton AB"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://maps.google.com/maps?output=embed&q=440+Hodgson+Blvd+NW+Edmonton+AB"
    )
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_maps_embed_rejects_empty_query() -> None:
    client = TestClient(app)

    response = client.get("/maps/embed", params={"query": "   "})

    assert response.status_code == 400


def test_maps_local_verify_uses_postal_lookup_and_suggests_correction() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "address_line": "15226 Royal Ave",
            "postal_code": "V4B 3Y4",
            "city": "Vancouver",
            "province": "BC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "local_postal_code_city_lookup"
    assert body["matched"] is True
    assert body["status"] == "corrected_by_postal_lookup"
    assert body["preferred_city"] == "White Rock"
    assert body["province"] == "BC"
    assert body["corrected_city"] == "White Rock"
    assert body["city_consistent"] is False
    assert "本地邮编库命中 V4B 3Y4 -> White Rock, BC" in body["note_zh"]


def test_maps_local_verify_returns_manual_note_when_postal_missing_from_lookup() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "G0S 2X0",
            "city": "Ste-Marguerite-De-Dorchester",
            "province": "QC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["status"] == "postal_not_found"
    assert body["postal_prefix"] == "G0S"
    assert body["province"] == "QC"
    assert body["risk_tags"] == ["postal_lookup_not_found"]


def build_client() -> TestClient:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        session.add(
            PostalCodeCityLookup(
                postal_code="V4B 3Y4",
                preferred_city="White Rock",
                province="BC",
                fsa="V4B",
                official_city="White Rock",
                source="test",
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
