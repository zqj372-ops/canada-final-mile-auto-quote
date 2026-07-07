import json
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, CityAlias, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from apps.api.main import app


def build_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), TestingSessionLocal


def teardown_function() -> None:
    app.dependency_overrides.clear()


def upload(client: TestClient, path: str, payload: object) -> dict[str, object]:
    response = client.post(
        path,
        files={"file": ("import.json", json.dumps(payload).encode("utf-8"), "application/json")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_import_zone_price_matrix_upserts_rows() -> None:
    client, SessionLocal = build_client()
    payload = {
        "source": "unit-test",
        "last_updated": "2026-07-06",
        "toronto": {"2": {"3": "120.00"}},
    }

    first = upload(client, "/imports/zone-price-matrix", payload)
    second = upload(client, "/imports/zone-price-matrix", {**payload, "source": "unit-test-updated"})

    assert first["inserted_count"] == 1
    assert second["updated_count"] == 1
    with SessionLocal() as session:
        records = session.scalars(select(ZonePriceMatrix)).all()
        assert len(records) == 1
        assert records[0].source == "unit-test-updated"


def test_import_zone_rules_upserts_rows() -> None:
    client, SessionLocal = build_client()
    payload = {
        "records": [
            {
                "postal_prefix": "L4K",
                "city": "Concord",
                "province": "ON",
                "origin": "Toronto",
                "zone": 2,
                "match_level": "demo",
                "note": "first",
            }
        ]
    }

    first = upload(client, "/imports/zone-rules", payload)
    payload["records"][0]["note"] = "updated"
    second = upload(client, "/imports/zone-rules", payload)

    assert first["inserted_count"] == 1
    assert second["updated_count"] == 1
    with SessionLocal() as session:
        records = session.scalars(select(ZoneLookupRule)).all()
        assert len(records) == 1
        assert records[0].canonical_city == "CONCORD"
        assert records[0].active is True
        assert records[0].note == "updated"


def test_import_postal_code_lookup_upserts_rows() -> None:
    client, SessionLocal = build_client()

    first = upload(client, "/imports/postal-code-lookup", {"L4K2N2": "Concord"})
    second = upload(client, "/imports/postal-code-lookup", {"L4K2N2": "Vaughan"})

    assert first["inserted_count"] == 1
    assert second["updated_count"] == 1
    with SessionLocal() as session:
        record = session.get(PostalCodeCityLookup, "L4K 2N2")
        assert record is not None
        assert record.preferred_city == "Vaughan"
        assert record.fsa == "L4K"


def test_import_city_aliases_upserts_rows() -> None:
    client, SessionLocal = build_client()
    payload = {
        "records": [
            {
                "province": "ON",
                "alias_city": "Concord",
                "canonical_city": "Vaughan",
                "alias_type": "suburb",
            }
        ]
    }

    first = upload(client, "/imports/city-aliases", payload)
    payload["records"][0]["canonical_city"] = "Vaughan"
    payload["records"][0]["note"] = "confirmed"
    second = upload(client, "/imports/city-aliases", payload)

    assert first["inserted_count"] == 1
    assert second["updated_count"] == 1
    with SessionLocal() as session:
        records = session.scalars(select(CityAlias)).all()
        assert len(records) == 1
        assert records[0].alias_city == "CONCORD"
        assert records[0].canonical_city == "VAUGHAN"
        assert records[0].note == "confirmed"
