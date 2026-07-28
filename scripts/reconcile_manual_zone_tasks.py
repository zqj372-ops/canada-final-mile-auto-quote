from __future__ import annotations

from argparse import ArgumentParser
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from pydantic import ValidationError
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask, ZoneLookupRule
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.db.session import get_session_factory
from apps.api.services.quote_logic_explainer import attach_zone_quote_logic
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_lookup import (
    ORIGIN_BY_PROVINCE,
    get_province_from_strict_fsa,
    normalize_origin,
)
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult, ZoneQuoteSourceType
from packages.address_normalizer import normalize_province


STALE_ZONE_MATCHED_BY = {
    "city_fallback_invalid_anchor",
    "city_fallback_expected_origin_not_found",
    "historical_task_non_exact_recheck",
    "origin_matrix_guard",
}
STALE_ZONE_RISK_TAGS = {
    "historical_task_non_exact_recheck",
    "zone_rule_province_mismatch",
    "origin_matrix_mismatch",
}
ALL_ZONE_RISK_TAGS = {
    *STALE_ZONE_RISK_TAGS,
    "zone_not_found",
    "split_record_conflict",
    "zone_price_not_found",
    "zone_price_disabled",
}
EXACT_MATCHED_BY = {"postal_code_override", "fsa_single_zone"}
TRUSTED_EXACT_MATCH_LEVELS = {
    "manual_correction",
    "production_audit_correction",
}
SAFE_INFORMATIONAL_RISK_TAGS = {
    "appointment_required",
    "liftgate_required",
    "pallet_jack_required",
    "residential",
    "rural_fsa_secondary_confirmation",
}
REQUIRED_MIGRATION = "0020_zone_reference_integrity"


def should_recheck(task: ManualQuoteTask, *, scope: str) -> bool:
    result = task.result_json if isinstance(task.result_json, dict) else {}
    matched_by = str(result.get("matched_by") or "")
    result_risk_tags = result.get("risk_tags") if isinstance(result.get("risk_tags"), list) else []
    risk_tags = {str(tag) for tag in [*(task.risk_tags or []), *result_risk_tags]}
    if scope == "stale-zone":
        legacy_reason = task.reason or ""
        return (
            matched_by in STALE_ZONE_MATCHED_BY
            or bool(risk_tags & STALE_ZONE_RISK_TAGS)
            or any(
                phrase in legacy_reason
                for phrase in (
                    "跨省旧 Zone 锚点",
                    "跨省脏记录",
                    "不符合省份始发仓",
                    "origin_matrix_guard",
                )
            )
        )
    return bool(risk_tags & ALL_ZONE_RISK_TAGS)


def reconcile_tasks(
    session: Session,
    *,
    scope: str,
    apply: bool,
    expected_eligible: int | None = None,
    expected_candidate_hash: str | None = None,
    expected_plan_hash: str | None = None,
) -> dict[str, Any]:
    scanned_tasks = list(
        session.scalars(
            select(ManualQuoteTask)
            .where(ManualQuoteTask.status.in_(("pending", "in_progress")))
            .order_by(ManualQuoteTask.id.asc())
        )
    )
    pending_tasks = [task for task in scanned_tasks if task.status == "pending"]
    eligible_preview = [task for task in pending_tasks if should_recheck(task, scope=scope)]
    in_progress_similar = [
        task.id
        for task in scanned_tasks
        if task.status == "in_progress" and should_recheck(task, scope=scope)
    ]
    if expected_eligible is not None and len(eligible_preview) != expected_eligible:
        raise RuntimeError(
            f"eligible task count changed: expected {expected_eligible}, "
            f"found {len(eligible_preview)}"
        )
    candidate_hash = _id_hash([task.id for task in eligible_preview])
    if expected_candidate_hash is not None and candidate_hash != expected_candidate_hash:
        raise RuntimeError(
            "candidate task set changed: "
            f"expected {expected_candidate_hash}, found {candidate_hash}"
        )

    tasks = eligible_preview
    if apply and eligible_preview:
        candidate_ids = [task.id for task in eligible_preview]
        tasks = list(
            session.scalars(
                select(ManualQuoteTask)
                .where(
                    ManualQuoteTask.id.in_(candidate_ids),
                    ManualQuoteTask.status == "pending",
                )
                .order_by(ManualQuoteTask.id.asc())
                .with_for_update(skip_locked=True)
            )
        )
        if len(tasks) != len(candidate_ids):
            raise RuntimeError(
                "One or more candidate tasks changed or are locked; aborting without writes."
            )

    pricing_config = QuoteRuleConfigRepository(session).get_zone_pricing_config()
    engine = ZoneQuoteEngine(ZoneRepository(session), pricing_config=pricing_config)
    report: dict[str, Any] = {
        "scope": scope,
        "apply": apply,
        "pending_scanned": len(pending_tasks),
        "eligible": len(eligible_preview),
        "candidate_task_ids": [task.id for task in eligible_preview],
        "candidate_id_hash": candidate_hash,
        "in_progress_similar_task_ids": in_progress_similar,
        "quoted_tasks_cancelled": 0,
        "manual_tasks_updated": 0,
        "skipped_human_touched": 0,
        "unchanged": 0,
        "invalid_request": 0,
        "changes": [],
    }
    plan_entries: list[dict[str, Any]] = []

    for task in tasks:
        if task.assigned_to or task.resolved_price_usd is not None or task.resolved_note:
            report["skipped_human_touched"] += 1
            entry = {"task_id": task.id, "action": "skipped_human_touched"}
            report["changes"].append(entry)
            plan_entries.append(
                {
                    **entry,
                    "input_hash": _task_input_hash(task),
                }
            )
            continue
        try:
            request = ZoneQuoteRequest.model_validate(task.request_json)
        except ValidationError as exc:
            report["invalid_request"] += 1
            entry = {
                "task_id": task.id,
                "action": "skipped_invalid_request",
                "error": str(exc),
            }
            report["changes"].append(entry)
            plan_entries.append(
                {
                    **entry,
                    "input_hash": _task_input_hash(task),
                }
            )
            continue

        result = engine.quote(request)
        result = result.model_copy(update={"quote_id": task.quote_id})
        result = preserve_non_zone_risk_tags(result, task.risk_tags or [])
        result = require_exact_match_before_cancelling(result)
        result = attach_zone_quote_logic(request, result)
        if not result.manual_review_required:
            result = mark_cancelled_reconciliation(result)
        result = attach_reconciliation_trace(task, result)
        result_json = result.model_dump(mode="json")
        old_result = task.result_json if isinstance(task.result_json, dict) else {}
        old_matched_by = old_result.get("matched_by")
        changed = (
            task.reason != result.matched_rule
            or list(task.risk_tags or []) != list(result.risk_tags)
            or old_result != result_json
        )

        if not changed:
            report["unchanged"] += 1
            plan_entries.append(
                {
                    "task_id": task.id,
                    "action": "unchanged",
                    "input_hash": _task_input_hash(task),
                    "result": result_json,
                }
            )
            continue

        if result.manual_review_required:
            action = "manual_task_updated"
            report["manual_tasks_updated"] += 1
        else:
            action = "cancelled_after_deterministic_requote"
            report["quoted_tasks_cancelled"] += 1

        entry = {
            "task_id": task.id,
            "action": action,
            "old_matched_by": old_matched_by,
            "new_matched_by": result.matched_by,
            "postal_code": request.postal_code,
            "city": request.city,
            "province": request.province,
            "origin": result.origin,
            "zone": result.zone,
            "confidence": result.confidence,
            "match_level": result.match_trace.get("matched_rule_match_level"),
            "risk_tags": result.risk_tags,
            "total_price_usd": (
                str(result.total_price_usd)
                if result.total_price_usd is not None
                else None
            ),
        }
        report["changes"].append(entry)
        plan_entries.append(
            {
                **entry,
                "input_hash": _task_input_hash(task),
                "result": result_json,
            }
        )
        if not apply:
            continue

        task.reason = result.matched_rule
        task.risk_tags = list(result.risk_tags)
        task.result_json = result_json
        if not result.manual_review_required:
            task.status = "cancelled"
            task.resolved_note = (
                "Zone 源数据修复后已由确定性引擎重新计算，旧人工任务作废；"
                "重算结果未向客户发送。"
            )

    plan_hash = _json_hash(plan_entries)
    report["plan_hash"] = plan_hash
    if expected_plan_hash is not None and plan_hash != expected_plan_hash:
        session.rollback()
        raise RuntimeError(
            f"reconciliation plan changed: expected {expected_plan_hash}, found {plan_hash}"
        )
    if apply:
        session.commit()
    else:
        session.rollback()
    return report


def require_exact_match_before_cancelling(result: ZoneQuoteResult) -> ZoneQuoteResult:
    """Keep legacy tasks open when a repair only creates a city-level fallback."""

    exact_match = result.matched_by in EXACT_MATCHED_BY
    if exact_match and result.matched_by == "fsa_single_zone":
        rule_city = str(result.match_trace.get("matched_rule_city") or "").strip().upper()
        destination_cities = [
            str(city).strip().upper()
            for city in (
                result.match_trace.get("input_city"),
                result.preferred_city,
                result.city,
            )
            if city
        ]
        match_level = str(
            result.match_trace.get("matched_rule_match_level") or ""
        ).strip().lower()
        exact_match = bool(
            rule_city
            and destination_cities
            and all(city == rule_city for city in destination_cities)
            and match_level in TRUSTED_EXACT_MATCH_LEVELS
        )
    blocking_non_zone_tags = {
        tag
        for tag in result.risk_tags
        if not _is_zone_derived_risk_tag(tag)
        and tag not in SAFE_INFORMATIONAL_RISK_TAGS
    }
    if blocking_non_zone_tags:
        exact_match = False
    if result.manual_review_required or exact_match:
        return result
    return result.model_copy(
        update={
            "source_type": ZoneQuoteSourceType.MANUAL_REQUIRED,
            "confidence": 0,
            "base_price_usd": None,
            "fuel_usd": None,
            "accessorials": {},
            "total_price_usd": None,
            "risk_tags": sorted(
                set([*result.risk_tags, "historical_task_non_exact_recheck"])
            ),
            "manual_review_required": True,
            "matched_rule": (
                "源数据修复后的结果未通过历史任务自动关闭门禁；该任务仍需人工确认，"
                "不能据此自动关闭或向客户发送。"
            ),
            "matched_by": "historical_task_non_exact_recheck",
            "match_trace": {
                **result.match_trace,
                "recomputed_matched_by": result.matched_by,
                "recomputed_matched_rule": result.matched_rule,
                "recomputed_confidence": result.confidence,
                "recomputed_city": result.city,
                "recomputed_preferred_city": result.preferred_city,
                "not_cancelled_reason": (
                    "Cancellation requires a trusted full-postal/same-city exact FSA "
                    "and no remaining non-Zone manual blocker."
                ),
                "blocking_non_zone_risk_tags": sorted(blocking_non_zone_tags),
                "matched_by": "historical_task_non_exact_recheck",
            },
            "sales_note": "历史人工任务未通过可信同城精确门禁，确认前不得向客户发送。",
            "internal_note": "重算未通过可信同城精确门禁，保留人工任务且清空金额。",
        }
    )


def preserve_non_zone_risk_tags(
    result: ZoneQuoteResult,
    original_risk_tags: list[str],
) -> ZoneQuoteResult:
    preserved = {
        str(tag)
        for tag in original_risk_tags
        if not _is_zone_derived_risk_tag(str(tag))
    }
    if not preserved:
        return result
    return result.model_copy(
        update={"risk_tags": sorted(set([*result.risk_tags, *preserved]))}
    )


def _is_zone_derived_risk_tag(tag: str) -> bool:
    return tag in {
        "split_record_conflict",
        "stale_origin_overridden",
        "nearest_postal_prefix_fallback",
    } or tag.startswith(
        (
            "zone_",
            "city_zone_",
            "postal_family_",
            "origin_matrix_",
            "expected_origin_",
            "historical_task_",
        )
    )


def mark_cancelled_reconciliation(result: ZoneQuoteResult) -> ZoneQuoteResult:
    trace = dict(result.match_trace)
    quote_logic = (
        dict(trace.get("quote_logic"))
        if isinstance(trace.get("quote_logic"), dict)
        else {}
    )
    quote_logic.update(
        {
            "status": "cancelled_reconciliation",
            "headline": "旧人工任务因规则修复已作废；本次重算未发送客户。",
            "next_action": "如需对客，请重新发起当前报价；禁止直接发送这条历史任务中的结果。",
        }
    )
    trace["quote_logic"] = quote_logic
    return result.model_copy(
        update={
            "match_trace": trace,
            "sales_note": "历史人工任务已作废；重算仅用于数据清理，未发送客户，禁止直接转发。",
            "internal_note": (
                "规则修复后精确重算成功，旧任务已取消；如需对客必须重新发起报价。"
            ),
        }
    )


def attach_reconciliation_trace(
    task: ManualQuoteTask,
    result: ZoneQuoteResult,
) -> ZoneQuoteResult:
    old_result = task.result_json if isinstance(task.result_json, dict) else {}
    old_trace = old_result.get("match_trace") if isinstance(old_result.get("match_trace"), dict) else {}
    existing = old_trace.get("reconciliation")
    reconciliation = (
        dict(existing)
        if isinstance(existing, dict)
        else {
            "original_matched_by": old_result.get("matched_by"),
            "original_reason": task.reason,
            "customer_notified": False,
        }
    )
    trace = {**result.match_trace, "reconciliation": reconciliation}
    return result.model_copy(update={"match_trace": trace})


def _id_hash(ids: list[int]) -> str:
    payload = ",".join(str(value) for value in sorted(ids))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _json_hash(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _task_input_hash(task: ManualQuoteTask) -> str:
    return _json_hash(
        {
            "id": task.id,
            "status": task.status,
            "assigned_to": task.assigned_to,
            "resolved_price_usd": task.resolved_price_usd,
            "resolved_note": task.resolved_note,
            "reason": task.reason,
            "risk_tags": task.risk_tags,
            "request_json": task.request_json,
            "result_json": task.result_json,
        }
    )


def verify_runtime_integrity(
    session: Session,
    *,
    lock_rules: bool,
    expected_zone_rule_hash: str | None = None,
) -> dict[str, Any]:
    if lock_rules:
        session.execute(
            text(
                """
                LOCK TABLE
                    zone_lookup_rules,
                    quote_rule_config,
                    zone_price_matrix,
                    postal_code_city_lookup,
                    postal_zone_overrides,
                    city_aliases
                IN SHARE MODE
                """
            )
        )
    version = session.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if version != REQUIRED_MIGRATION:
        raise RuntimeError(
            f"required migration {REQUIRED_MIGRATION} is not active; found {version}"
        )

    invalid_ids: list[int] = []
    active_rules = list(
        session.scalars(
            select(ZoneLookupRule)
            .where(ZoneLookupRule.active.is_(True))
            .order_by(ZoneLookupRule.id.asc())
        )
    )
    for rule in active_rules:
        inferred_province = get_province_from_strict_fsa(rule.postal_prefix)
        province = normalize_province(rule.province)
        expected_origin = ORIGIN_BY_PROVINCE.get(province or "")
        if (
            inferred_province is None
            or province is None
            or inferred_province != province
            or (expected_origin and normalize_origin(rule.origin) != expected_origin)
        ):
            invalid_ids.append(rule.id)
    if invalid_ids:
        raise RuntimeError(
            f"active Zone integrity errors remain: count={len(invalid_ids)} "
            f"examples={invalid_ids[:10]}"
        )
    zone_rule_hash = hashlib.sha256(
        json.dumps(
            [
                [
                    rule.id,
                    rule.postal_prefix,
                    rule.city,
                    rule.province,
                    normalize_origin(rule.origin),
                    rule.zone,
                    rule.canonical_city,
                    rule.priority,
                    rule.match_level,
                    rule.note,
                ]
                for rule in active_rules
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    if expected_zone_rule_hash is not None and zone_rule_hash != expected_zone_rule_hash:
        raise RuntimeError(
            "active Zone rule set changed: "
            f"expected {expected_zone_rule_hash}, found {zone_rule_hash}"
        )
    return {
        "migration": version,
        "active_zone_integrity_errors": 0,
        "active_zone_rule_count": len(active_rules),
        "active_zone_rule_hash": zone_rule_hash,
        "database": session.get_bind().url.render_as_string(hide_password=True),
    }


def main() -> None:
    parser = ArgumentParser(
        description=(
            "Re-evaluate pending Zone manual tasks without quote audits, learning writes, "
            "or customer notifications."
        )
    )
    parser.add_argument(
        "--scope",
        choices=("stale-zone", "all-zone"),
        default="stale-zone",
    )
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--expect-eligible", type=int)
    parser.add_argument("--expect-candidate-hash")
    parser.add_argument("--expect-zone-rule-hash")
    parser.add_argument("--expect-plan-hash")
    args = parser.parse_args()
    if args.apply and (
        args.expect_eligible is None
        or not args.expect_candidate_hash
        or not args.expect_zone_rule_hash
        or not args.expect_plan_hash
    ):
        parser.error(
            "--apply requires --expect-eligible, --expect-candidate-hash, and "
            "--expect-zone-rule-hash, and --expect-plan-hash from the immediately "
            "preceding dry-run"
        )

    session_factory = get_session_factory()
    with session_factory() as session:
        session.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"))
        session.execute(text("SET LOCAL lock_timeout = '5s'"))
        runtime = verify_runtime_integrity(
            session,
            lock_rules=args.apply,
            expected_zone_rule_hash=args.expect_zone_rule_hash,
        )
        report = reconcile_tasks(
            session,
            scope=args.scope,
            apply=args.apply,
            expected_eligible=args.expect_eligible,
            expected_candidate_hash=args.expect_candidate_hash,
            expected_plan_hash=args.expect_plan_hash,
        )
        report["runtime"] = runtime
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
