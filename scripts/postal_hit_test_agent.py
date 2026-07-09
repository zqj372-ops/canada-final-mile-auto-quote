from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.db.models import PostalCodeCityLookup
from apps.api.db.repositories.hermes_diagnostic_repository import HermesDiagnosticRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.db.session import get_session_factory
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_lookup import ORIGIN_BY_PROVINCE
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


TZ = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class CargoProfile:
    name: str
    cbm: Decimal
    weight_kg: Decimal
    piece_count: int
    packaging_type: str
    longest_side_cm: Decimal
    explicit_pallet_count: int | None = None


PROFILES: dict[str, CargoProfile] = {
    "1p": CargoProfile(
        name="1p",
        cbm=Decimal("1.70"),
        weight_kg=Decimal("200"),
        piece_count=1,
        packaging_type="carton",
        longest_side_cm=Decimal("170"),
    ),
    "3p": CargoProfile(
        name="3p",
        cbm=Decimal("3.80"),
        weight_kg=Decimal("1100"),
        piece_count=20,
        packaging_type="carton",
        longest_side_cm=Decimal("144"),
    ),
    "6p": CargoProfile(
        name="6p",
        cbm=Decimal("10.90"),
        weight_kg=Decimal("2270"),
        piece_count=200,
        packaging_type="carton",
        longest_side_cm=Decimal("50"),
    ),
}

FALLBACK_RISK_TAGS = {
    "city_zone_fallback",
    "city_zone_prefix_family_fallback",
    "postal_family_fallback",
    "nearest_postal_prefix_fallback",
    "expected_origin_preferred",
    "stale_origin_overridden",
}


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Run random Canada postal-code quote diagnostics and produce Hermes-style "
            "learning suggestions. The script never changes price tables or publishes rules."
        )
    )
    parser.add_argument("--sample-size", type=int, default=5000)
    parser.add_argument("--profiles", default="1p", help="Comma-separated cargo profiles: 1p,3p,6p.")
    parser.add_argument("--province", default=None, help="Optional province filter, e.g. BC or SK.")
    parser.add_argument("--output-dir", default="outputs/postal_hit_tests")
    parser.add_argument("--persist-diagnostics", action="store_true")
    parser.add_argument(
        "--persist-only",
        choices=["all", "anomalies", "manual"],
        default="anomalies",
        help="When persisting diagnostics, choose which observations to enqueue.",
    )
    parser.add_argument("--min-support", type=int, default=3, help="Support threshold for rule suggestions.")
    args = parser.parse_args()

    profiles = _parse_profiles(args.profiles)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    batch_id = datetime.now(TZ).strftime("%Y%m%d%H%M%S")
    with get_session_factory()() as session:
        records = _sample_postal_records(session, sample_size=args.sample_size, province=args.province)
        observations = _run_observations(session, records, profiles=profiles, batch_id=batch_id)
        report = build_report(
            observations,
            batch_id=batch_id,
            requested_sample_size=args.sample_size,
            profiles=[profile.name for profile in profiles],
            min_support=args.min_support,
        )
        if args.persist_diagnostics:
            report["persisted_diagnostic_count"] = persist_diagnostics(
                session,
                observations,
                batch_id=batch_id,
                persist_only=args.persist_only,
            )

    json_path = output_dir / f"postal_hit_test_{batch_id}.json"
    md_path = output_dir / f"postal_hit_test_{batch_id}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    md_path.write_text(render_markdown_report(report), encoding="utf-8")
    print(json.dumps(_console_summary(report, json_path, md_path), ensure_ascii=False, indent=2))


def _parse_profiles(value: str) -> list[CargoProfile]:
    names = [item.strip() for item in value.split(",") if item.strip()]
    profiles: list[CargoProfile] = []
    for name in names:
        if name not in PROFILES:
            raise SystemExit(f"Unknown profile {name!r}. Available: {', '.join(sorted(PROFILES))}")
        profiles.append(PROFILES[name])
    return profiles or [PROFILES["1p"]]


def _sample_postal_records(
    session: Session,
    *,
    sample_size: int,
    province: str | None,
) -> list[tuple[str, str, str | None]]:
    statement = select(
        PostalCodeCityLookup.postal_code,
        PostalCodeCityLookup.preferred_city,
        PostalCodeCityLookup.province,
    )
    if province:
        statement = statement.where(PostalCodeCityLookup.province == province.strip().upper())
    statement = statement.order_by(func.random()).limit(max(1, sample_size))
    return [(postal_code, city, prov) for postal_code, city, prov in session.execute(statement).all()]


def _run_observations(
    session: Session,
    records: list[tuple[str, str, str | None]],
    *,
    profiles: list[CargoProfile],
    batch_id: str,
) -> list[dict[str, Any]]:
    engine = ZoneQuoteEngine(ZoneRepository(session))
    observations: list[dict[str, Any]] = []
    for index, (postal_code, city, province) in enumerate(records, start=1):
        profile = profiles[(index - 1) % len(profiles)]
        request = ZoneQuoteRequest(
            address_line=f"Postal hit test {postal_code}",
            postal_code=postal_code,
            city=city,
            province=province,
            cbm=profile.cbm,
            weight_kg=profile.weight_kg,
            piece_count=profile.piece_count,
            packaging_type=profile.packaging_type,
            longest_side_cm=profile.longest_side_cm,
            explicit_pallet_count=profile.explicit_pallet_count,
            address_type="commercial",
            requires_liftgate=False,
            requires_pallet_jack=False,
            requires_appointment=False,
        )
        result = engine.quote(request)
        result.quote_id = f"hit-{batch_id}-{index:05d}"
        observations.append(_observation_from_result(index, profile, request, result))
    return observations


def _observation_from_result(
    index: int,
    profile: CargoProfile,
    request: ZoneQuoteRequest,
    result: ZoneQuoteResult,
) -> dict[str, Any]:
    source_type = result.source_type.value if hasattr(result.source_type, "value") else str(result.source_type)
    risk_tags = list(result.risk_tags or [])
    return {
        "index": index,
        "profile": profile.name,
        "quote_id": result.quote_id,
        "postal_code": request.postal_code,
        "postal_prefix": result.postal_prefix,
        "input_city": request.city,
        "city": result.city,
        "province": result.province or request.province,
        "expected_origin": ORIGIN_BY_PROVINCE.get((result.province or request.province or "").upper()),
        "source_type": source_type,
        "manual_review_required": result.manual_review_required,
        "matched_by": result.matched_by,
        "origin": result.origin,
        "zone": result.zone,
        "billing_pallets": result.billing_pallets,
        "base_price_usd": _decimal_string(result.base_price_usd),
        "fuel_usd": _decimal_string(result.fuel_usd),
        "total_price_usd": _decimal_string(result.total_price_usd),
        "confidence": result.confidence,
        "candidate_count": result.candidate_count,
        "risk_tags": risk_tags,
        "matched_rule": result.matched_rule,
        "match_trace": result.match_trace,
        "is_anomaly": _is_anomaly(result),
        "quote_request": request.model_dump(mode="json"),
        "quote_result": result.model_dump(mode="json"),
    }


def build_report(
    observations: list[dict[str, Any]],
    *,
    batch_id: str,
    requested_sample_size: int,
    profiles: list[str],
    min_support: int,
) -> dict[str, Any]:
    counters = {
        "source_type": Counter(),
        "matched_by": Counter(),
        "province": Counter(),
        "origin_zone": Counter(),
        "risk_tags": Counter(),
        "profile": Counter(),
    }
    manual_clusters: dict[tuple[Any, ...], dict[str, Any]] = {}
    fallback_clusters: dict[tuple[Any, ...], dict[str, Any]] = {}
    price_gap_clusters: dict[tuple[Any, ...], dict[str, Any]] = {}
    expected_origin_clusters: dict[tuple[Any, ...], dict[str, Any]] = {}

    quoted = 0
    manual = 0
    anomalies = 0
    for item in observations:
        counters["source_type"][item["source_type"]] += 1
        counters["matched_by"][item.get("matched_by") or "unknown"] += 1
        counters["province"][item.get("province") or "unknown"] += 1
        counters["profile"][item["profile"]] += 1
        if item.get("origin") and item.get("zone") is not None:
            counters["origin_zone"][f"{item['origin']} Zone {item['zone']}"] += 1
        for tag in item.get("risk_tags") or []:
            counters["risk_tags"][tag] += 1
        if item["manual_review_required"]:
            manual += 1
            _add_cluster(
                manual_clusters,
                (
                    item.get("matched_by"),
                    item.get("postal_prefix"),
                    item.get("city"),
                    item.get("province"),
                    item.get("billing_pallets"),
                    item.get("matched_rule"),
                ),
                item,
            )
        else:
            quoted += 1
        if item["is_anomaly"]:
            anomalies += 1
        if item.get("risk_tags") and set(item["risk_tags"]) & FALLBACK_RISK_TAGS:
            _add_cluster(
                fallback_clusters,
                (
                    item.get("matched_by"),
                    item.get("postal_prefix"),
                    item.get("city"),
                    item.get("province"),
                    item.get("origin"),
                    item.get("zone"),
                    item.get("billing_pallets"),
                ),
                item,
            )
        if "expected_origin_preferred" in (item.get("risk_tags") or []):
            _add_cluster(
                expected_origin_clusters,
                (
                    item.get("postal_prefix"),
                    item.get("city"),
                    item.get("province"),
                    item.get("origin"),
                    item.get("zone"),
                ),
                item,
            )
        if "zone_price_not_found" in (item.get("risk_tags") or []):
            _add_cluster(
                price_gap_clusters,
                (item.get("origin"), item.get("zone"), item.get("billing_pallets")),
                item,
            )

    suggestions = _build_learning_suggestions(
        fallback_clusters=fallback_clusters,
        expected_origin_clusters=expected_origin_clusters,
        price_gap_clusters=price_gap_clusters,
        manual_clusters=manual_clusters,
        min_support=min_support,
    )
    return {
        "schema_version": "2026-07-09.postal-hit-test-agent.v1",
        "batch_id": batch_id,
        "generated_at": datetime.now(TZ).isoformat(),
        "requested_sample_size": requested_sample_size,
        "actual_sample_size": len(observations),
        "profiles": profiles,
        "summary": {
            "quoted": quoted,
            "manual_required": manual,
            "anomalies": anomalies,
            "quote_success_rate": _rate(quoted, len(observations)),
            "manual_required_rate": _rate(manual, len(observations)),
        },
        "counters": {name: _counter_dict(counter) for name, counter in counters.items()},
        "top_manual_clusters": _top_clusters(manual_clusters, limit=40),
        "top_fallback_clusters": _top_clusters(fallback_clusters, limit=40),
        "top_expected_origin_clusters": _top_clusters(expected_origin_clusters, limit=40),
        "top_price_gap_clusters": _top_clusters(price_gap_clusters, limit=40),
        "learning_suggestions": suggestions,
        "sample_anomalies": [item for item in observations if item["is_anomaly"]][:120],
        "sample_observations": observations[:120],
        "policy": {
            "price_tables_changed": False,
            "learned_rules_published": False,
            "note": "This run only diagnoses and proposes review candidates. It never changes zone_price_matrix or publishes learned rules.",
        },
    }


def _build_learning_suggestions(
    *,
    fallback_clusters: dict[tuple[Any, ...], dict[str, Any]],
    expected_origin_clusters: dict[tuple[Any, ...], dict[str, Any]],
    price_gap_clusters: dict[tuple[Any, ...], dict[str, Any]],
    manual_clusters: dict[tuple[Any, ...], dict[str, Any]],
    min_support: int,
) -> list[dict[str, Any]]:
    suggestions: list[dict[str, Any]] = []
    for cluster in _top_clusters(expected_origin_clusters, limit=80):
        if cluster["count"] < min_support:
            continue
        example = cluster["examples"][0]
        suggestions.append(
            {
                "action": "review_expected_origin_formalization",
                "priority": "high" if cluster["count"] >= min_support * 3 else "medium",
                "support_count": cluster["count"],
                "postal_prefix": example.get("postal_prefix"),
                "city": example.get("city"),
                "province": example.get("province"),
                "suggested_origin": example.get("origin"),
                "suggested_zone": example.get("zone"),
                "reason_zh": "同一场景多次依靠省份始发仓过滤旧记录后命中唯一 Zone，建议人工确认后固化或清理旧锚点。",
                "example_quote_id": example.get("quote_id"),
            }
        )
    for cluster in _top_clusters(fallback_clusters, limit=80):
        if cluster["count"] < min_support:
            continue
        example = cluster["examples"][0]
        suggestions.append(
            {
                "action": "review_fallback_zone_rule",
                "priority": "medium",
                "support_count": cluster["count"],
                "postal_prefix": example.get("postal_prefix"),
                "city": example.get("city"),
                "province": example.get("province"),
                "suggested_origin": example.get("origin"),
                "suggested_zone": example.get("zone"),
                "billing_pallets": example.get("billing_pallets"),
                "reason_zh": "随机命中测试重复依赖城市/邮编族模糊回退，建议后台审核是否补充正式 Zone 规则。",
                "example_quote_id": example.get("quote_id"),
            }
        )
    for cluster in _top_clusters(price_gap_clusters, limit=80):
        example = cluster["examples"][0]
        suggestions.append(
            {
                "action": "fill_zone_price_matrix_after_supplier_confirmation",
                "priority": "high",
                "support_count": cluster["count"],
                "suggested_origin": example.get("origin"),
                "suggested_zone": example.get("zone"),
                "billing_pallets": example.get("billing_pallets"),
                "reason_zh": "Zone 已命中但价格矩阵缺少对应托数价格。只能提示补表，不能自动估价。",
                "example_quote_id": example.get("quote_id"),
            }
        )
    for cluster in _top_clusters(manual_clusters, limit=80):
        if cluster["count"] < min_support:
            continue
        example = cluster["examples"][0]
        suggestions.append(
            {
                "action": "manual_cluster_review",
                "priority": "medium",
                "support_count": cluster["count"],
                "postal_prefix": example.get("postal_prefix"),
                "city": example.get("city"),
                "province": example.get("province"),
                "matched_by": example.get("matched_by"),
                "reason_zh": "同类 manual_required 重复出现，建议运营复核后决定补 Zone、补价格矩阵或保持人工。",
                "example_quote_id": example.get("quote_id"),
            }
        )
    return sorted(suggestions, key=lambda item: (-int(item["support_count"]), item["action"]))[:120]


def persist_diagnostics(
    session: Session,
    observations: list[dict[str, Any]],
    *,
    batch_id: str,
    persist_only: str,
) -> int:
    repository = HermesDiagnosticRepository(session)
    persisted = 0
    for item in observations:
        if persist_only == "manual" and not item["manual_review_required"]:
            continue
        if persist_only == "anomalies" and not item["is_anomaly"]:
            continue
        package = _diagnostic_package(item, batch_id=batch_id)
        record = repository.create(
            quote_id=item["quote_id"],
            quote_status="manual_required" if item["manual_review_required"] else "quoted",
            source_type=item["source_type"],
            diagnostic_package_json=package,
        )
        repository.save_suggestion(
            record.id,
            status="completed",
            suggestion=_agent_suggestion(item),
        )
        persisted += 1
    return persisted


def _diagnostic_package(item: dict[str, Any], *, batch_id: str) -> dict[str, Any]:
    return {
        "schema_version": "2026-07-09.postal-hit-test-diagnostic.v1",
        "source": "postal_hit_test_agent",
        "batch_id": batch_id,
        "profile": item["profile"],
        "quote_id": item["quote_id"],
        "quote_status": "manual_required" if item["manual_review_required"] else "quoted",
        "quote_request": item["quote_request"],
        "quote_result": item["quote_result"],
        "address": {
            "postal_code": item["postal_code"],
            "postal_prefix": item["postal_prefix"],
            "city": item["city"],
            "province": item["province"],
            "expected_origin_by_province": item["expected_origin"],
        },
        "zone_hit": {
            "matched_by": item["matched_by"],
            "matched_rule": item["matched_rule"],
            "candidate_count": item["candidate_count"],
            "origin": item["origin"],
            "zone": item["zone"],
            "match_trace": item["match_trace"],
        },
        "failure": {
            "manual_review_required": item["manual_review_required"],
            "reason": item["matched_rule"] if item["manual_review_required"] else None,
            "risk_tags": item["risk_tags"],
        },
        "agent_contract": {
            "role": "Diagnose postal-code coverage and propose review items only.",
            "forbidden_actions": ["change_price", "publish_learned_rule", "modify_zone_price_matrix"],
        },
    }


def _agent_suggestion(item: dict[str, Any]) -> dict[str, Any]:
    if item["manual_review_required"]:
        action = "manual_review"
        reason = "该邮编测试未能自动报价，需要人工判断是否补 Zone 或补价格矩阵。"
    elif set(item.get("risk_tags") or []) & FALLBACK_RISK_TAGS:
        action = "review_rule_formalization"
        reason = "该邮编可报价，但依赖模糊/旧记录过滤逻辑，建议纳入规则整理。"
    else:
        action = "no_action"
        reason = "正常命中 Zone 价格矩阵。"
    return {
        "suggested_action": action,
        "can_auto_correct": False,
        "confidence": item.get("confidence") or 0,
        "reason_zh": reason,
        "suggested_origin": item.get("origin"),
        "suggested_zone": item.get("zone"),
        "missing_table": "zone_price_matrix" if "zone_price_not_found" in (item.get("risk_tags") or []) else None,
        "recommend_manual_review": item["manual_review_required"] or action != "no_action",
        "recommend_learning_candidate": False,
        "notes": [
            "随机邮编命中测试不会自动发布学习规则。",
            "只有人工任务 resolved 后才允许生成可审核学习候选。",
        ],
    }


def render_markdown_report(report: dict[str, Any]) -> str:
    summary = report["summary"]
    lines = [
        f"# Postal Hit Test Agent Report {report['batch_id']}",
        "",
        "## Summary",
        "",
        f"- 样本数：{report['actual_sample_size']} / requested {report['requested_sample_size']}",
        f"- 成功报价：{summary['quoted']} ({summary['quote_success_rate']})",
        f"- 需要人工：{summary['manual_required']} ({summary['manual_required_rate']})",
        f"- 异常/模糊命中：{summary['anomalies']}",
        f"- 测试货量 profiles：{', '.join(report['profiles'])}",
        "",
        "## Top Matched By",
        "",
        *[f"- {key}: {value}" for key, value in list(report["counters"]["matched_by"].items())[:20]],
        "",
        "## Top Risk Tags",
        "",
        *[f"- {key}: {value}" for key, value in list(report["counters"]["risk_tags"].items())[:20]],
        "",
        "## Learning Suggestions",
        "",
    ]
    if report["learning_suggestions"]:
        for item in report["learning_suggestions"][:40]:
            lines.append(
                f"- [{item['priority']}] {item['action']} | support={item['support_count']} | "
                f"{item.get('postal_prefix') or '-'} {item.get('city') or '-'} {item.get('province') or '-'} "
                f"-> {item.get('suggested_origin') or '-'} Zone {item.get('suggested_zone') or '-'} | "
                f"{item['reason_zh']}"
            )
    else:
        lines.append("- 暂无达到支持阈值的整理建议。")
    lines.extend(
        [
            "",
            "## Policy",
            "",
            "- 本报告不修改 `zone_price_matrix`。",
            "- 本报告不发布 `learned_quote_rules`。",
            "- 所有建议必须经人工审核。",
        ]
    )
    return "\n".join(lines) + "\n"


def _add_cluster(
    clusters: dict[tuple[Any, ...], dict[str, Any]],
    key: tuple[Any, ...],
    item: dict[str, Any],
) -> None:
    cluster = clusters.setdefault(
        key,
        {
            "key": [str(value) if value is not None else None for value in key],
            "count": 0,
            "examples": [],
            "risk_tags": Counter(),
        },
    )
    cluster["count"] += 1
    for tag in item.get("risk_tags") or []:
        cluster["risk_tags"][tag] += 1
    if len(cluster["examples"]) < 6:
        cluster["examples"].append(_compact_observation(item))


def _top_clusters(clusters: dict[tuple[Any, ...], dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    rows = sorted(clusters.values(), key=lambda item: (-item["count"], item["key"]))
    result = []
    for item in rows[:limit]:
        result.append(
            {
                "key": item["key"],
                "count": item["count"],
                "risk_tags": _counter_dict(item["risk_tags"]),
                "examples": item["examples"],
            }
        )
    return result


def _compact_observation(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "quote_id": item["quote_id"],
        "postal_code": item["postal_code"],
        "postal_prefix": item.get("postal_prefix"),
        "city": item.get("city"),
        "province": item.get("province"),
        "matched_by": item.get("matched_by"),
        "origin": item.get("origin"),
        "zone": item.get("zone"),
        "billing_pallets": item.get("billing_pallets"),
        "base_price_usd": item.get("base_price_usd"),
        "total_price_usd": item.get("total_price_usd"),
        "risk_tags": item.get("risk_tags") or [],
        "matched_rule": item.get("matched_rule"),
    }


def _is_anomaly(result: ZoneQuoteResult) -> bool:
    if result.manual_review_required:
        return True
    return bool(set(result.risk_tags or []) & FALLBACK_RISK_TAGS)


def _counter_dict(counter: Counter) -> dict[str, int]:
    return {str(key): int(value) for key, value in counter.most_common()}


def _rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00%"
    return f"{numerator / denominator * 100:.2f}%"


def _decimal_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(value):.2f}"


def _json_default(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _console_summary(report: dict[str, Any], json_path: Path, md_path: Path) -> dict[str, Any]:
    return {
        "batch_id": report["batch_id"],
        "summary": report["summary"],
        "learning_suggestion_count": len(report["learning_suggestions"]),
        "persisted_diagnostic_count": report.get("persisted_diagnostic_count", 0),
        "json_report": str(json_path),
        "markdown_report": str(md_path),
        "top_matched_by": dict(list(report["counters"]["matched_by"].items())[:10]),
        "top_risk_tags": dict(list(report["counters"]["risk_tags"].items())[:10]),
    }


if __name__ == "__main__":
    main()
