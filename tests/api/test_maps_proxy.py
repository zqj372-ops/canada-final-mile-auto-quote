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
    assert body["risk_tags"] == [
        "postal_lookup_not_found",
        "rural_fsa_secondary_confirmation",
    ]
    assert "邮编前缀 G0S 第二位为 0" in body["note_zh"]
    assert "必须再次确认完整地址" in body["note_zh"]


def test_maps_local_verify_flags_exact_rural_postal_match_for_secondary_confirmation() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "N0A 1M0",
            "city": "Ohsweken",
            "province": "ON",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["status"] == "verified"
    assert body["confidence"] == 95
    assert body["risk_tags"] == [
        "local_postal_verified",
        "rural_fsa_secondary_confirmation",
    ]
    assert "二次确认提醒" in body["note_zh"]


def test_maps_local_verify_recognizes_v3x0l7_as_surrey() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "V3X 0L7",
            "city": "Surrey",
            "province": "BC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["status"] == "verified"
    assert body["confidence"] == 95
    assert body["preferred_city"] == "Surrey"
    assert body["province"] == "BC"
    assert body["city_consistent"] is True
    assert body["province_consistent"] is True
    assert body["risk_tags"] == ["local_postal_verified"]
    assert "本地邮编库命中 V3X 0L7 -> Surrey, BC" in body["note_zh"]


def test_maps_local_verify_recognizes_v3j0a7_as_burnaby() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "V3J 0A7",
            "city": "Burnaby",
            "province": "BC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is True
    assert body["status"] == "verified"
    assert body["confidence"] == 95
    assert body["preferred_city"] == "Burnaby"
    assert body["province"] == "BC"
    assert body["city_consistent"] is True
    assert body["province_consistent"] is True
    assert body["risk_tags"] == ["local_postal_verified"]


def test_maps_local_verify_suggests_city_for_unanimous_fsa_only() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "V9Z 0C3",
            "province": "BC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["status"] == "postal_fsa_suggested"
    assert body["confidence"] == 70
    assert body["preferred_city"] == "Sooke"
    assert body["source"] == "local_postal_fsa_consensus"
    assert body["fsa_city_counts"] == {"Sooke": 20}
    assert body["risk_tags"] == ["postal_lookup_not_found", "fsa_city_consensus"]
    assert "20 条记录全部对应 Sooke, BC" in body["note_zh"]
    assert "不覆盖 Zone 或价格规则" in body["note_zh"]


def test_maps_local_verify_keeps_rural_warning_on_fsa_city_suggestion() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "T0A 0C3",
            "province": "AB",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "postal_fsa_suggested"
    assert body["preferred_city"] == "Smoky Lake"
    assert body["risk_tags"] == [
        "postal_lookup_not_found",
        "fsa_city_consensus",
        "rural_fsa_secondary_confirmation",
    ]
    assert "邮编前缀 T0A 第二位为 0" in body["note_zh"]


def test_maps_local_verify_does_not_guess_for_multi_city_fsa() -> None:
    client = build_client()

    response = client.get(
        "/maps/local-verify",
        params={
            "postal_code": "V8Y 0C3",
            "province": "BC",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["matched"] is False
    assert body["status"] == "postal_not_found"
    assert body["confidence"] == 25
    assert body["preferred_city"] is None
    assert body["fsa_city_counts"] == {"Saanich": 10, "Victoria": 10}
    assert body["risk_tags"] == ["postal_lookup_not_found", "fsa_multiple_cities"]
    assert "不能仅按邮编前缀推断城市" in body["note_zh"]


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
        session.add(
            PostalCodeCityLookup(
                postal_code="N0A 1M0",
                preferred_city="Ohsweken",
                province="ON",
                fsa="N0A",
                official_city="Ohsweken",
                source="test_rural_exact",
            )
        )
        session.add(
            PostalCodeCityLookup(
                postal_code="V3X 0L7",
                preferred_city="Surrey",
                province="BC",
                fsa="V3X",
                official_city="Surrey",
                source="manual_postal_correction_20260720",
            )
        )
        session.add(
            PostalCodeCityLookup(
                postal_code="V3J 0A7",
                preferred_city="Burnaby",
                province="BC",
                fsa="V3J",
                official_city="Burnaby",
                source="manual_postal_correction_20260720",
            )
        )
        for letter in "AB":
            for digit in range(10):
                session.add(
                    PostalCodeCityLookup(
                        postal_code=f"V9Z 0{letter}{digit}",
                        preferred_city="Sooke",
                        province="BC",
                        fsa="V9Z",
                        official_city="Sooke",
                        source="test_fsa_consensus",
                    )
                )
        for letter in "AB":
            for digit in range(10):
                session.add(
                    PostalCodeCityLookup(
                        postal_code=f"T0A 0{letter}{digit}",
                        preferred_city="Smoky Lake",
                        province="AB",
                        fsa="T0A",
                        official_city="Smoky Lake",
                        source="test_rural_fsa_consensus",
                    )
                )
        for digit in range(10):
            session.add(
                PostalCodeCityLookup(
                    postal_code=f"V8Y 0A{digit}",
                    preferred_city="Victoria",
                    province="BC",
                    fsa="V8Y",
                    official_city="Victoria",
                    source="test_fsa_multiple_cities",
                )
            )
            session.add(
                PostalCodeCityLookup(
                    postal_code=f"V8Y 0B{digit}",
                    preferred_city="Saanich",
                    province="BC",
                    fsa="V8Y",
                    official_city="Saanich",
                    source="test_fsa_multiple_cities",
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
