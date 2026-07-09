from __future__ import annotations

import json
from collections.abc import Generator
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, HermesDiagnosticQueue
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


def test_batch_diagnostic_report_reads_json_file(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report_dir = tmp_path / "postal_hit_tests"
    report_dir.mkdir()
    monkeypatch.setenv("POSTAL_HIT_TEST_OUTPUT_DIR", str(report_dir))
    report = {
        "batch_id": "20260709164939",
        "generated_at": "2026-07-09T16:50:00+08:00",
        "requested_sample_size": 5000,
        "actual_sample_size": 5000,
        "profiles": ["1p"],
        "summary": {
            "quoted": 4692,
            "manual_required": 308,
            "anomalies": 3185,
            "quote_success_rate": "93.84%",
            "manual_required_rate": "6.16%",
        },
        "counters": {"matched_by": {"postal_prefix": 10}, "risk_tags": {"zone_price_not_found": 3}},
        "top_manual_clusters": [],
        "top_fallback_clusters": [],
        "top_expected_origin_clusters": [],
        "top_price_gap_clusters": [
            {
                "count": 3,
                "examples": [
                    {
                        "quote_id": "hit-20260709164939-00001",
                        "postal_prefix": "S7K",
                        "city": "Saskatoon",
                        "origin": "calgary",
                        "zone": 5,
                        "risk_tags": ["zone_price_not_found"],
                    }
                ],
            }
        ],
        "learning_suggestions": [{"action": "manual_cluster_review", "support_count": 3}],
        "sample_anomalies": [{"quote_id": "hit-20260709164939-00001"}],
        "sample_observations": [],
        "policy": {"price_tables_changed": False, "learned_rules_published": False},
    }
    (report_dir / "postal_hit_test_20260709164939.json").write_text(
        json.dumps(report),
        encoding="utf-8",
    )
    client, _ = build_client()

    reports = client.get("/quotes/batch-diagnostic-reports")
    detail = client.get("/quotes/batch-diagnostic-reports/20260709164939")

    assert reports.status_code == 200
    body = reports.json()
    assert body[0]["batch_id"] == "20260709164939"
    assert body[0]["actual_sample_size"] == 5000
    assert body[0]["report_available"] is True
    assert detail.status_code == 200
    assert detail.json()["learning_suggestion_count"] == 1
    assert detail.json()["top_price_gap_clusters"][0]["count"] == 3


def test_batch_diagnostic_report_falls_back_to_diagnostic_queue(
    tmp_path: Path,
    monkeypatch,
) -> None:
    report_dir = tmp_path / "empty"
    report_dir.mkdir()
    monkeypatch.setenv("POSTAL_HIT_TEST_OUTPUT_DIR", str(report_dir))
    client, SessionLocal = build_client()
    with SessionLocal() as session:
        session.add(
            HermesDiagnosticQueue(
                quote_id="hit-20260709170000-00001",
                quote_status="manual_required",
                source_type="manual_required",
                status="completed",
                diagnostic_package_json={
                    "source": "postal_hit_test_agent",
                    "batch_id": "20260709170000",
                    "profile": "1p",
                    "address": {
                        "postal_code": "S7K 1X6",
                        "postal_prefix": "S7K",
                        "city": "Saskatoon",
                        "province": "SK",
                    },
                    "quote_result": {
                        "billing_pallets": 1,
                        "risk_tags": ["zone_price_not_found"],
                    },
                    "zone_hit": {
                        "matched_by": "postal_prefix",
                        "origin": "calgary",
                        "zone": 5,
                        "matched_rule": "Zone price not found",
                    },
                    "failure": {
                        "manual_review_required": True,
                        "reason": "Zone price not found",
                        "risk_tags": ["zone_price_not_found"],
                    },
                },
                agent_suggestion_json={
                    "suggested_action": "manual_review",
                    "reason_zh": "价格矩阵缺少对应托数。",
                    "suggested_origin": "calgary",
                    "suggested_zone": 5,
                },
            )
        )
        session.commit()

    reports = client.get("/quotes/batch-diagnostic-reports").json()
    detail = client.get("/quotes/batch-diagnostic-reports/20260709170000").json()

    assert reports[0]["batch_id"] == "20260709170000"
    assert reports[0]["report_available"] is False
    assert reports[0]["diagnostic_count"] == 1
    assert detail["sample_anomalies"][0]["postal_prefix"] == "S7K"
    assert detail["learning_suggestions"][0]["reason_zh"] == "价格矩阵缺少对应托数。"
