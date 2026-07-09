from __future__ import annotations

import json
import os
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import HermesDiagnosticQueue


MAX_DB_DIAGNOSTICS = 5000


def list_batch_diagnostic_reports(db: Session) -> list[dict[str, object]]:
    reports_by_batch: dict[str, dict[str, object]] = {}
    for path in _report_files():
        report = _load_report_file(path)
        if not report:
            continue
        summary = _summary_from_report(report, source="file")
        summary["file_path"] = str(path)
        reports_by_batch[str(summary["batch_id"])] = summary

    for batch_id, records in _diagnostic_records_by_batch(db).items():
        if batch_id in reports_by_batch:
            reports_by_batch[batch_id]["diagnostic_count"] = len(records)
            continue
        reports_by_batch[batch_id] = _summary_from_diagnostics(batch_id, records)

    return sorted(
        reports_by_batch.values(),
        key=lambda item: str(item.get("generated_at") or item.get("batch_id") or ""),
        reverse=True,
    )


def get_batch_diagnostic_report(db: Session, batch_id: str) -> dict[str, object]:
    safe_batch_id = batch_id.strip()
    if not safe_batch_id:
        raise HTTPException(status_code=404, detail="Batch diagnostic report not found.")

    for path in _report_files():
        report = _load_report_file(path)
        if report and str(report.get("batch_id")) == safe_batch_id:
            detail = _normalize_report_detail(report)
            detail["source"] = "file"
            detail["file_path"] = str(path)
            detail["diagnostic_count"] = len(_diagnostic_records_by_batch(db).get(safe_batch_id, []))
            return detail

    records = _diagnostic_records_by_batch(db).get(safe_batch_id, [])
    if records:
        return _detail_from_diagnostics(safe_batch_id, records)

    raise HTTPException(status_code=404, detail="Batch diagnostic report not found.")


def _report_files() -> list[Path]:
    roots = [
        os.getenv("POSTAL_HIT_TEST_OUTPUT_DIR"),
        "/app/outputs/postal_hit_tests",
        "outputs/postal_hit_tests",
    ]
    files: list[Path] = []
    seen: set[Path] = set()
    for root in roots:
        if not root:
            continue
        path = Path(root).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        if not path.is_dir():
            continue
        for item in sorted(path.glob("postal_hit_test_*.json"), reverse=True):
            resolved = item.resolve()
            if resolved not in seen:
                seen.add(resolved)
                files.append(resolved)
    return files


def _load_report_file(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) and data.get("batch_id") else None


def _diagnostic_records_by_batch(db: Session) -> dict[str, list[HermesDiagnosticQueue]]:
    records = db.scalars(
        select(HermesDiagnosticQueue)
        .order_by(HermesDiagnosticQueue.created_at.desc(), HermesDiagnosticQueue.id.desc())
        .limit(MAX_DB_DIAGNOSTICS)
    ).all()
    grouped: dict[str, list[HermesDiagnosticQueue]] = defaultdict(list)
    for record in records:
        package = record.diagnostic_package_json or {}
        if package.get("source") != "postal_hit_test_agent":
            continue
        batch_id = _text(package.get("batch_id"))
        if batch_id:
            grouped[batch_id].append(record)
    return grouped


def _summary_from_report(report: dict[str, Any], *, source: str) -> dict[str, object]:
    summary = _object(report.get("summary"))
    return {
        "batch_id": _text(report.get("batch_id")) or "-",
        "generated_at": _text(report.get("generated_at")),
        "source": source,
        "report_available": source == "file",
        "requested_sample_size": _int(report.get("requested_sample_size")),
        "actual_sample_size": _int(report.get("actual_sample_size")),
        "quoted": _int(summary.get("quoted")),
        "manual_required": _int(summary.get("manual_required")),
        "anomalies": _int(summary.get("anomalies")),
        "quote_success_rate": _text(summary.get("quote_success_rate")),
        "manual_required_rate": _text(summary.get("manual_required_rate")),
        "learning_suggestion_count": len(_list(report.get("learning_suggestions"))),
        "persisted_diagnostic_count": _int(report.get("persisted_diagnostic_count")),
        "diagnostic_count": 0,
        "profiles": _list(report.get("profiles")),
    }


def _summary_from_diagnostics(batch_id: str, records: list[HermesDiagnosticQueue]) -> dict[str, object]:
    manual = sum(1 for record in records if record.quote_status == "manual_required")
    quoted = sum(1 for record in records if record.quote_status == "quoted")
    total = len(records)
    generated_at = max((_datetime_text(record.created_at) for record in records if record.created_at), default=None)
    return {
        "batch_id": batch_id,
        "generated_at": generated_at,
        "source": "diagnostic_queue",
        "report_available": False,
        "requested_sample_size": None,
        "actual_sample_size": total,
        "quoted": quoted,
        "manual_required": manual,
        "anomalies": total,
        "quote_success_rate": _rate(quoted, total),
        "manual_required_rate": _rate(manual, total),
        "learning_suggestion_count": sum(1 for record in records if record.agent_suggestion_json),
        "persisted_diagnostic_count": total,
        "diagnostic_count": total,
        "profiles": sorted({str((record.diagnostic_package_json or {}).get("profile")) for record in records if (record.diagnostic_package_json or {}).get("profile")}),
    }


def _normalize_report_detail(report: dict[str, Any]) -> dict[str, object]:
    detail = _summary_from_report(report, source="file")
    detail.update(
        {
            "counters": _object(report.get("counters")),
            "top_manual_clusters": _list(report.get("top_manual_clusters")),
            "top_fallback_clusters": _list(report.get("top_fallback_clusters")),
            "top_expected_origin_clusters": _list(report.get("top_expected_origin_clusters")),
            "top_price_gap_clusters": _list(report.get("top_price_gap_clusters")),
            "learning_suggestions": _list(report.get("learning_suggestions")),
            "sample_anomalies": _list(report.get("sample_anomalies")),
            "sample_observations": _list(report.get("sample_observations")),
            "policy": _object(report.get("policy")),
        }
    )
    return detail


def _detail_from_diagnostics(batch_id: str, records: list[HermesDiagnosticQueue]) -> dict[str, object]:
    detail = _summary_from_diagnostics(batch_id, records)
    observations = [_observation_from_diagnostic(record) for record in records]
    detail.update(
        {
            "counters": _counters_from_observations(observations),
            "top_manual_clusters": _cluster_observations(observations, manual_only=True),
            "top_fallback_clusters": _cluster_observations(observations, fallback_only=True),
            "top_expected_origin_clusters": [],
            "top_price_gap_clusters": _cluster_observations(observations, price_gap_only=True),
            "learning_suggestions": [_suggestion_from_diagnostic(record) for record in records if record.agent_suggestion_json][:80],
            "sample_anomalies": observations[:120],
            "sample_observations": observations[:120],
            "policy": {
                "price_tables_changed": False,
                "learned_rules_published": False,
                "note": "This view was rebuilt from persisted diagnostic queue records; full random-test report JSON was not visible to the API container.",
            },
        }
    )
    return detail


def _observation_from_diagnostic(record: HermesDiagnosticQueue) -> dict[str, object]:
    package = record.diagnostic_package_json or {}
    address = _object(package.get("address"))
    result = _object(package.get("quote_result"))
    zone_hit = _object(package.get("zone_hit"))
    failure = _object(package.get("failure"))
    risk_tags = _list(failure.get("risk_tags") or result.get("risk_tags"))
    return {
        "quote_id": record.quote_id,
        "postal_code": address.get("postal_code"),
        "postal_prefix": address.get("postal_prefix"),
        "city": address.get("city"),
        "province": address.get("province"),
        "source_type": record.source_type,
        "manual_review_required": record.quote_status == "manual_required",
        "matched_by": zone_hit.get("matched_by") or result.get("matched_by"),
        "origin": zone_hit.get("origin") or result.get("origin"),
        "zone": zone_hit.get("zone") or result.get("zone"),
        "billing_pallets": result.get("billing_pallets"),
        "base_price_usd": result.get("base_price_usd"),
        "total_price_usd": result.get("total_price_usd"),
        "confidence": result.get("confidence") or record.confidence,
        "risk_tags": risk_tags,
        "matched_rule": zone_hit.get("matched_rule") or failure.get("reason"),
    }


def _counters_from_observations(observations: list[dict[str, object]]) -> dict[str, dict[str, int]]:
    counters = {
        "source_type": Counter(),
        "matched_by": Counter(),
        "province": Counter(),
        "origin_zone": Counter(),
        "risk_tags": Counter(),
    }
    for item in observations:
        counters["source_type"][_text(item.get("source_type")) or "unknown"] += 1
        counters["matched_by"][_text(item.get("matched_by")) or "unknown"] += 1
        counters["province"][_text(item.get("province")) or "unknown"] += 1
        if item.get("origin") and item.get("zone") is not None:
            counters["origin_zone"][f"{item['origin']} Zone {item['zone']}"] += 1
        for tag in _list(item.get("risk_tags")):
            counters["risk_tags"][str(tag)] += 1
    return {name: dict(counter.most_common()) for name, counter in counters.items()}


def _cluster_observations(
    observations: list[dict[str, object]],
    *,
    manual_only: bool = False,
    fallback_only: bool = False,
    price_gap_only: bool = False,
) -> list[dict[str, object]]:
    fallback_tags = {"city_zone_fallback", "city_zone_prefix_family_fallback", "postal_family_fallback", "nearest_postal_prefix_fallback", "expected_origin_preferred", "stale_origin_overridden"}
    clusters: dict[tuple[object, ...], dict[str, object]] = {}
    for item in observations:
        tags = {str(tag) for tag in _list(item.get("risk_tags"))}
        if manual_only and not item.get("manual_review_required"):
            continue
        if fallback_only and not (tags & fallback_tags):
            continue
        if price_gap_only and "zone_price_not_found" not in tags:
            continue
        key = (
            item.get("matched_by"),
            item.get("postal_prefix"),
            item.get("city"),
            item.get("province"),
            item.get("origin"),
            item.get("zone"),
            item.get("billing_pallets"),
        )
        cluster = clusters.setdefault(
            key,
            {"key": [str(value) if value is not None else None for value in key], "count": 0, "risk_tags": {}, "examples": []},
        )
        cluster["count"] = int(cluster["count"]) + 1
        risk_counter = Counter(cluster["risk_tags"])
        risk_counter.update(tags)
        cluster["risk_tags"] = dict(risk_counter.most_common())
        examples = cluster["examples"]
        if isinstance(examples, list) and len(examples) < 6:
            examples.append(item)
    return sorted(clusters.values(), key=lambda item: (-int(item["count"]), str(item["key"])))[:40]


def _suggestion_from_diagnostic(record: HermesDiagnosticQueue) -> dict[str, object]:
    suggestion = record.agent_suggestion_json or {}
    package = record.diagnostic_package_json or {}
    address = _object(package.get("address"))
    return {
        "action": suggestion.get("suggested_action") or suggestion.get("action") or "manual_review",
        "priority": "medium",
        "support_count": 1,
        "postal_prefix": address.get("postal_prefix"),
        "city": address.get("city"),
        "province": address.get("province"),
        "suggested_origin": suggestion.get("suggested_origin"),
        "suggested_zone": suggestion.get("suggested_zone"),
        "reason_zh": suggestion.get("reason_zh") or "诊断队列已有建议，请人工确认。",
        "example_quote_id": record.quote_id,
    }


def _object(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _list(value: object) -> list[Any]:
    return value if isinstance(value, list) else []


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _datetime_text(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00%"
    return f"{numerator / denominator * 100:.2f}%"
