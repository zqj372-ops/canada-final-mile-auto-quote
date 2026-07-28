import json
from collections.abc import Generator

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, CityAlias, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.session import get_db
from apps.api.main import app
from apps.api.routes.imports import _upsert_rows
from packages.data_importer.zone_loader import build_zone_indexes


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


def upload_table(
    client: TestClient,
    path: str,
    content: bytes,
    *,
    filename: str = "zone-prices.csv",
) -> dict[str, object]:
    response = client.post(
        path,
        files={"file": (filename, content, "text/csv")},
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
    record = {
        "postal_prefix": "L4K",
        "city": "CONCORD",
        "province": "ON",
        "origin": "Toronto",
        "zone": 2,
        "match_level": "demo",
        "note": "first",
    }
    payload = {
        "total_records": 1,
        "records": [record],
        "data": build_zone_indexes([record]),
    }

    first = upload(client, "/imports/zone-rules", payload)
    payload["records"][0]["note"] = "updated"
    payload["data"] = build_zone_indexes(payload["records"])
    second = upload(client, "/imports/zone-rules", payload)

    assert first["inserted_count"] == 1
    assert second["updated_count"] == 1
    with SessionLocal() as session:
        records = session.scalars(select(ZoneLookupRule)).all()
        assert len(records) == 1
        assert records[0].canonical_city == "CONCORD"
        assert records[0].active is True
        assert records[0].note == "updated"


def test_zone_rule_upsert_prefers_active_duplicate() -> None:
    _, SessionLocal = build_client()
    key = {
        "postal_prefix": "H8R",
        "city": "LACHINE",
        "province": "QC",
        "origin": "toronto",
        "zone": 7,
    }
    with SessionLocal() as session:
        session.add_all(
            [
                ZoneLookupRule(**key, active=False, note="quarantined duplicate"),
                ZoneLookupRule(**key, active=True, note="active winner"),
            ]
        )
        session.commit()

        result = _upsert_rows(
            session,
            ZoneLookupRule,
            [{**key, "active": True, "note": "updated winner"}],
            key_fields=("postal_prefix", "city", "province", "origin", "zone"),
            update_fields=("active", "note"),
        )

        records = list(
            session.scalars(select(ZoneLookupRule).order_by(ZoneLookupRule.id.asc()))
        )
        assert result["updated_count"] == 1
        assert records[0].active is False
        assert records[0].note == "quarantined duplicate"
        assert records[1].active is True
        assert records[1].note == "updated winner"


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


def test_preview_and_import_zone_price_spreadsheet() -> None:
    client, SessionLocal = build_client()
    upload(
        client,
        "/imports/zone-price-matrix",
        {
            "source": "seed",
            "last_updated": "2026-07-01",
            "toronto": {"2": {"1": "120.00"}},
        },
    )
    spreadsheet = (
        "始发仓,Zone,燃油附加比例(%),1托,2托,来源备注,更新日期\n"
        "toronto,2,37.5,125,180,供应商七月价,2026-07-17\n"
        "calgary,1,40,99,,供应商七月价,2026-07-17\n"
    ).encode("utf-8-sig")

    preview = upload_table(client, "/imports/zone-price-matrix/preview", spreadsheet)

    assert preview["can_import"] is True
    assert preview["source_row_count"] == 2
    assert preview["row_count"] == 3
    assert preview["inserted_count"] == 2
    assert preview["updated_count"] == 1
    assert preview["fuel_override_count"] == 2

    imported = upload_table(client, "/imports/zone-price-matrix", spreadsheet)

    assert imported["inserted_count"] == 2
    assert imported["updated_count"] == 1
    assert imported["fuel_updated_count"] == 2
    with SessionLocal() as session:
        records = session.scalars(select(ZonePriceMatrix)).all()
        assert len(records) == 3
        toronto_one_pallet = next(
            record
            for record in records
            if record.origin == "toronto" and record.zone == 2 and record.billing_pallets == 1
        )
        assert str(toronto_one_pallet.base_price_usd) == "125.00"
        pricing = QuoteRuleConfigRepository(session).get_zone_pricing_config()
        assert str(pricing.fuel_percent_by_zone["toronto|2"]) == "37.5"
        assert str(pricing.fuel_percent_by_zone["calgary|1"]) == "40"


def test_zone_price_spreadsheet_conflicting_fuel_is_rejected() -> None:
    client, _ = build_client()
    spreadsheet = (
        "始发仓,Zone,燃油附加比例(%),1托,2托\n"
        "toronto,2,35,120,\n"
        "toronto,2,40,,180\n"
    ).encode("utf-8-sig")

    preview = upload_table(client, "/imports/zone-price-matrix/preview", spreadsheet)

    assert preview["can_import"] is False
    assert preview["invalid_row_count"] == 1
    assert "燃油比例不一致" in preview["errors"][0]["message"]
    response = client.post(
        "/imports/zone-price-matrix",
        files={"file": ("zone-prices.csv", spreadsheet, "text/csv")},
    )
    assert response.status_code == 422
