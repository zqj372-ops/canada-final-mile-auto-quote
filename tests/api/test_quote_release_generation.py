from collections.abc import Generator
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from io import StringIO
import importlib.util
import inspect
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import (
    APIKey,
    Base,
    CityAlias,
    PostalCodeCityLookup,
    PostalZoneOverride,
    QuoteRuleConfig,
    QuoteReleaseManifest,
    QuoteSourceGeneration,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.session import get_db
from apps.api.db.source_generation import ensure_source_generation_row, install_source_generation_triggers
from apps.api.main import app
from apps.api.security.api_keys import hash_api_key
from apps.api.services import source_status_service
from tests.api.test_zone_quotes import base_payload, build_client


def _configure_release(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("QUOTE_RELEASE_ID", "release-20260812-a")
    monkeypatch.setenv("DEPLOY_SHA", "release-20260812-a")
    monkeypatch.setenv("QUOTE_VALID_FROM", date.today().isoformat())
    monkeypatch.setenv("QUOTE_VALID_TO", (date.today() + timedelta(days=30)).isoformat())
    monkeypatch.setenv("QUOTE_RELEASE_HASH", "auto")
    monkeypatch.setenv("QUOTE_TEST_DATA", "false")
    monkeypatch.setenv("DEV_AUTH_DISABLED", "true")
    monkeypatch.setattr(source_status_service, "_installed_service_version", lambda: "0.1.0")


def test_status_and_preview_do_not_scan_source_data(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_release(monkeypatch)
    client = build_client()
    calls = 0

    def forbidden(_db: Session) -> str:
        nonlocal calls
        calls += 1
        raise AssertionError("request path must not compute the full source hash")

    monkeypatch.setattr(source_status_service, "source_data_hash", forbidden)

    assert client.get("/status").status_code == 200
    assert client.post(
        "/quotes/zone-preview",
        json={
            "tenant_id": "default",
            "origin": "toronto",
            "effective_date": date.today().isoformat(),
            "quote": base_payload(),
        },
    ).status_code == 200
    assert calls == 0


def _build_published_client() -> tuple[TestClient, sessionmaker[Session]]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_source_generation_row(connection)
        install_source_generation_triggers(connection)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

    with TestingSessionLocal() as session:
        session.add(
            APIKey(
                name="Preview Sales",
                key_hash=hash_api_key("caq_sales_test_key"),
                role="sales",
                tenant_id="default",
                scopes=["quote:preview"],
                enabled=True,
            )
        )
        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        session.add(
            ZoneLookupRule(
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                match_level="release",
            )
        )
        session.add(
            ZonePriceMatrix(
                origin="toronto",
                zone=2,
                billing_pallets=3,
                base_price_usd=Decimal("120.00"),
                source="release",
            )
        )
        session.add(
            PostalZoneOverride(
                postal_code="L4K 2N2",
                postal_prefix="L4K",
                province="ON",
                origin="toronto",
                zone=2,
                source="release",
            )
        )
        session.add(CityAlias(province="ON", alias_city="VAUGHAN", canonical_city="CONCORD", source="release"))
        session.add(QuoteRuleConfig(key="fuel_percent", value="35", description="release"))
        session.commit()
        from apps.api.services.quote_release_service import publish_quote_release

        publish_quote_release(
            session,
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=30),
            test_data=False,
        )

    def override_get_db() -> Generator[Session]:
        with TestingSessionLocal() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app, headers={"X-API-Key": "caq_sales_test_key"}), TestingSessionLocal


@pytest.mark.parametrize("table", ["postal", "override", "alias", "rule", "price", "config"])
def test_source_table_change_invalidates_active_release(
    monkeypatch: pytest.MonkeyPatch,
    table: str,
) -> None:
    _configure_release(monkeypatch)
    client, TestingSessionLocal = _build_published_client()

    with TestingSessionLocal() as session:
        if table == "postal":
            record = session.get(PostalCodeCityLookup, "L4K 2N2")
            assert record is not None
            record.preferred_city = "Concord Updated"
        elif table == "override":
            record = session.query(PostalZoneOverride).one()
            record.zone = 3
        elif table == "alias":
            record = session.query(CityAlias).one()
            record.canonical_city = "VAUGHAN"
        elif table == "rule":
            record = session.query(ZoneLookupRule).one()
            record.zone = 3
        elif table == "price":
            record = session.query(ZonePriceMatrix).one()
            record.base_price_usd = Decimal("121.00")
        else:
            record = session.get(QuoteRuleConfig, "fuel_percent")
            assert record is not None
            record.value = "36"
        session.commit()

    assert client.get("/status").json()["ready"] is False
    preview = client.post(
        "/quotes/zone-preview",
        json={
            "tenant_id": "default",
            "origin": "toronto",
            "effective_date": date.today().isoformat(),
            "quote": base_payload(),
        },
    )
    assert preview.status_code == 503
    assert "release_manifest_source_generation_mismatch" in preview.json()["reasons"]


def test_publish_quote_release_hashes_source_once(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_release(monkeypatch)
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_source_generation_row(connection)
        install_source_generation_triggers(connection)
    TestingSessionLocal = sessionmaker(bind=engine, expire_on_commit=False)
    with TestingSessionLocal() as session:
        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        session.add(
            ZoneLookupRule(
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                match_level="release",
            )
        )
        session.add(
            ZonePriceMatrix(
                origin="toronto",
                zone=2,
                billing_pallets=3,
                base_price_usd=Decimal("120.00"),
                source="release",
            )
        )
        session.commit()
        calls = 0
        original = source_status_service.source_data_hash

        def counted(db: Session) -> str:
            nonlocal calls
            calls += 1
            return original(db)

        monkeypatch.setattr(source_status_service, "source_data_hash", counted)
        from apps.api.services.quote_release_service import publish_quote_release

        manifest = publish_quote_release(
            session,
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today() + timedelta(days=30),
            test_data=False,
        )

        assert calls == 1
        assert manifest.snapshot_hash.startswith("sha256:")
        assert manifest.source_generation == 3


def test_publish_requires_explicit_test_data_declaration(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_release(monkeypatch)
    from apps.api.services.quote_release_service import publish_quote_release

    with pytest.raises(ValueError, match="test_data_declaration_required"):
        publish_quote_release(
            Session(),
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today(),
        )


def test_publish_test_data_declaration_cannot_override_demo_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_release(monkeypatch)
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_source_generation_row(connection)
        install_source_generation_triggers(connection)
    with Session(bind=engine) as session:
        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        session.add(
            ZoneLookupRule(
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                match_level="demo",
            )
        )
        session.add(
            ZonePriceMatrix(
                origin="toronto",
                zone=2,
                billing_pallets=3,
                base_price_usd=Decimal("120.00"),
                source="release",
            )
        )
        session.commit()
        from apps.api.services.quote_release_service import publish_quote_release

        manifest = publish_quote_release(
            session,
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today(),
            test_data=False,
        )

        assert manifest.test_data is True


@pytest.mark.parametrize(
    ("record_type", "marker"),
    [("postal", "Demo Seed"), ("rule", "UNIT-TEST"), ("price", "fixture data")],
)
def test_publish_detects_compound_test_data_tokens(
    monkeypatch: pytest.MonkeyPatch,
    record_type: str,
    marker: str,
) -> None:
    _configure_release(monkeypatch)
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_source_generation_row(connection)
        install_source_generation_triggers(connection)
    with Session(bind=engine) as session:
        session.add(
            PostalCodeCityLookup(
                postal_code="L4K 2N2",
                preferred_city="Concord",
                province="ON",
                source=marker if record_type == "postal" else "release",
            )
        )
        session.add(
            ZoneLookupRule(
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                match_level=marker if record_type == "rule" else "release",
            )
        )
        session.add(
            ZonePriceMatrix(
                origin="toronto",
                zone=2,
                billing_pallets=3,
                base_price_usd=Decimal("120.00"),
                source=marker if record_type == "price" else "release",
            )
        )
        session.commit()
        from apps.api.services.quote_release_service import publish_quote_release

        manifest = publish_quote_release(
            session,
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today(),
            test_data=False,
        )

        assert manifest.test_data is True


def test_source_hash_is_stable_and_streaming() -> None:
    assert ".all(" not in inspect.getsource(source_status_service.source_data_hash)
    assert ".all(" not in inspect.getsource(source_status_service._hash_table)
    assert "stream_results=True" in inspect.getsource(source_status_service._hash_table)
    assert ".all(" not in inspect.getsource(
        source_status_service.QuoteRuleConfigRepository._get_standalone_zone_pricing_config
    )

    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(bind=engine) as session:
        session.add(PostalCodeCityLookup(postal_code="L4K 2N2", preferred_city="Concord", province="ON"))
        session.add(
            ZoneLookupRule(
                postal_prefix="L4K",
                city="CONCORD",
                province="ON",
                origin="toronto",
                zone=2,
                match_level="release",
            )
        )
        session.add(
            ZonePriceMatrix(
                origin="toronto",
                zone=2,
                billing_pallets=3,
                base_price_usd=Decimal("120.00"),
                source="release",
            )
        )
        session.commit()

        first = source_status_service.source_data_hash(session)
        second = source_status_service.source_data_hash(session)

        assert first == second


@pytest.mark.parametrize(
    ("env_key", "manifest_overrides", "reason"),
    [
        ("QUOTE_RELEASE_ID", {}, "deployment_config_missing:QUOTE_RELEASE_ID"),
        (None, {"release_id": "other-release"}, "deployment_config_mismatch:QUOTE_RELEASE_ID"),
        (None, {"service_version": "0.2.0"}, "release_manifest_service_version_mismatch"),
    ],
)
def test_release_identity_must_match_installed_build(
    monkeypatch: pytest.MonkeyPatch,
    env_key: str | None,
    manifest_overrides: dict[str, object],
    reason: str,
) -> None:
    _configure_release(monkeypatch)
    if env_key:
        monkeypatch.delenv(env_key, raising=False)
    client = build_client(manifest_overrides=manifest_overrides)

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert reason in response.json()["reasons"]


def test_release_status_fails_closed_when_build_metadata_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_release(monkeypatch)
    monkeypatch.setattr(source_status_service, "_installed_service_version", lambda: None)
    client = build_client()

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert "service_version_metadata_unavailable" in response.json()["reasons"]


def test_release_status_requires_deployed_commit_binding(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_release(monkeypatch)
    monkeypatch.delenv("DEPLOY_SHA")
    missing = build_client().get("/status").json()
    assert missing["ready"] is False
    assert "deployment_config_missing:DEPLOY_SHA" in missing["reasons"]

    monkeypatch.setenv("DEPLOY_SHA", "different-deploy-sha")
    mismatched = build_client().get("/status").json()
    assert mismatched["ready"] is False
    assert "deployment_config_mismatch:DEPLOY_SHA" in mismatched["reasons"]


def test_publish_rejects_missing_release_identity_or_service_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_release(monkeypatch)
    from apps.api.services.quote_release_service import publish_quote_release

    monkeypatch.delenv("QUOTE_RELEASE_ID", raising=False)
    with pytest.raises(ValueError, match="deployment_config_missing:QUOTE_RELEASE_ID"):
        publish_quote_release(
            Session(),
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today(),
            test_data=False,
        )

    monkeypatch.setenv("QUOTE_RELEASE_ID", "release-20260812-a")
    monkeypatch.setattr(source_status_service, "_installed_service_version", lambda: None)
    with pytest.raises(ValueError, match="service_version_metadata_unavailable"):
        publish_quote_release(
            Session(),
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today(),
            test_data=False,
        )


def test_postgres_generation_trigger_is_statement_level() -> None:
    spec = importlib.util.spec_from_file_location(
        "quote_source_generation_migration",
        "migrations/versions/0026_quote_source_generation.py",
    )
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    output = StringIO()
    context = MigrationContext.configure(
        dialect_name="postgresql",
        opts={"as_sql": True, "output_buffer": output},
    )
    operations = Operations(context)
    with Operations.context(operations):
        migration._create_postgresql_triggers()

    sql = output.getvalue()
    assert "FOR EACH STATEMENT" in sql
    assert "FOR EACH ROW" not in sql
    assert sql.count("CREATE TRIGGER") == 6
    assert "UPDATE quote_release_manifest SET active = FALSE WHERE active = TRUE" in Path(
        "migrations/versions/0026_quote_source_generation.py"
    ).read_text()


def test_pre_migration_active_manifest_is_not_ready_after_safety_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _configure_release(monkeypatch)
    client, TestingSessionLocal = _build_published_client()

    with TestingSessionLocal() as session:
        session.execute(text("UPDATE quote_release_manifest SET active = FALSE WHERE active = TRUE"))
        session.commit()

    response = client.get("/status")

    assert response.status_code == 200
    assert response.json()["ready"] is False
    assert "release_manifest_missing" in response.json()["reasons"]


def test_publish_rejects_deployed_commit_mismatch(monkeypatch: pytest.MonkeyPatch) -> None:
    _configure_release(monkeypatch)
    monkeypatch.setenv("DEPLOY_SHA", "different-deploy-sha")
    from apps.api.services.quote_release_service import publish_quote_release

    with pytest.raises(ValueError, match="deployment_config_mismatch:DEPLOY_SHA"):
        publish_quote_release(
            Session(),
            release_id="release-20260812-a",
            service_version="0.1.0",
            rule_version="rules-1",
            data_version="data-1",
            published_at=datetime.now(timezone.utc),
            valid_from=date.today(),
            valid_to=date.today(),
            test_data=False,
        )


def test_status_evidence_reads_do_not_take_postgres_locks() -> None:
    from apps.api.db.models import QuoteReleaseManifest

    generation_statement = select(QuoteSourceGeneration).where(QuoteSourceGeneration.id == 1)
    manifest_statement = (
        select(QuoteReleaseManifest)
        .where(QuoteReleaseManifest.active.is_(True))
        .limit(2)
    )

    for statement in (generation_statement, manifest_statement):
        sql = str(statement.compile(dialect=postgresql.dialect()))
        assert "FOR SHARE" not in sql
        assert "FOR UPDATE" not in sql


def test_publish_cli_help_and_missing_required_arguments() -> None:
    script = Path("scripts/publish_quote_release.py")
    help_result = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
    missing_result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)

    assert help_result.returncode == 0
    assert "--release-id" in help_result.stdout
    assert "--test-data" in help_result.stdout
    assert missing_result.returncode != 0


def teardown_module() -> None:
    app.dependency_overrides.clear()
