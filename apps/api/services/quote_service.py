from __future__ import annotations

import logging
from decimal import Decimal

from apps.api.db.models import LearnedQuoteRule
from apps.api.db.repositories.learned_quote_rule_repository import LearnedQuoteRuleRepository
from sqlalchemy.orm import Session

from apps.api.db.repositories.manual_quote_task_repository import ManualQuoteTaskRepository
from apps.api.db.repositories.quote_audit_repository import QuoteAuditRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.rate_rule_repository import RateRuleRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from apps.api.services.hermes_diagnostic_service import enqueue_quote_diagnostic
from apps.api.services.notification_service import (
    notify_manual_required,
    notify_quote_success,
    requested_notification_channels,
)
from apps.api.services.quote_logic_explainer import attach_zone_quote_logic
from packages.quote_engine.engine import QuoteEngine
from packages.quote_engine.models import QuoteCalculationRequest, QuoteResult, ShipmentInput
from packages.quote_engine.risk_tags import RURAL_FSA_SECONDARY_CONFIRMATION_TAG, rural_fsa_risk_tags
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_engine import ZoneQuoteEngine, build_zone_price_disabled_reason
from packages.quote_engine.zone_lookup import (
    ORIGIN_BY_PROVINCE,
    get_province_from_postal_code,
    normalize_origin,
    origin_label,
)
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult, ZoneQuoteSourceType
from apps.api.services.source_status_service import (
    SourceStatus,
    get_source_status,
    source_data_hash,
    source_status_version_key,
)


logger = logging.getLogger(__name__)


def calculate_vendor_quote(db: Session, shipment: ShipmentInput) -> QuoteResult:
    candidate_rules = RateRuleRepository(db).list_candidate_rules(shipment)
    request = QuoteCalculationRequest(shipment=shipment, rate_rules=candidate_rules)
    return QuoteEngine().quote(request)


def calculate_zone_quote(
    db: Session,
    payload: ZoneQuoteRequest,
    *,
    notify_email: bool = False,
    email_config_id: int | None = None,
    notify_wecom: bool = False,
    wecom_bot_id: int | None = None,
    persist_side_effects: bool = True,
    use_learned_rules: bool = True,
) -> ZoneQuoteResult:
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    result = ZoneQuoteEngine(ZoneRepository(db), pricing_config=pricing_config).quote(payload)
    if use_learned_rules:
        result = apply_learned_quote_if_available(
            db,
            payload,
            result,
            mark_used=persist_side_effects,
            rollback_on_error=persist_side_effects,
        )
    result = enforce_origin_matrix_safety(payload, result)
    result = enforce_zone_price_switch(pricing_config, result)
    result = attach_zone_quote_logic(payload, result)
    if persist_side_effects:
        record_zone_quote_side_effects(
            db,
            payload,
            result,
            source="zone_quote",
            manual_email_config_id=email_config_id,
            manual_wecom_bot_id=wecom_bot_id,
        )
        if (notify_email or notify_wecom) and not result.manual_review_required:
            try_notification(
                "quote_success",
                lambda: notify_quote_success(
                    db,
                    result=result,
                    request=payload,
                    bot_id=wecom_bot_id,
                    email_config_id=email_config_id,
                    channels=requested_notification_channels(email=notify_email, wecom=notify_wecom),
                ),
                result.quote_id,
            )
    return result


def calculate_zone_quote_preview(
    db: Session,
    payload: ZoneQuoteRequest,
    *,
    origin: str,
) -> tuple[SourceStatus, ZoneQuoteResult | None, list[str]]:
    status = get_source_status(db)
    if not status.ready:
        return status, None, list(status.reasons)

    before_data_hash = source_data_hash(db)
    try:
        result = calculate_zone_quote(
            db,
            payload,
            persist_side_effects=False,
            use_learned_rules=False,
        )
    except Exception:
        logger.exception("Read-only zone quote preview failed.")
        return status, None, ["quote_preview_failed"]

    after_data_hash = source_data_hash(db)
    if before_data_hash != after_data_hash:
        return status, None, ["source_data_changed_during_calculation"]
    if source_status_version_key(get_source_status(db)) != source_status_version_key(status):
        return status, None, ["source_version_changed_during_calculation"]
    if result.origin is not None and normalize_origin(result.origin) != origin:
        return status, None, ["origin_mismatch"]
    return status, result, []


def apply_learned_quote_if_available(
    db: Session,
    payload: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    *,
    mark_used: bool = True,
    rollback_on_error: bool = True,
) -> ZoneQuoteResult:
    try:
        repository = LearnedQuoteRuleRepository(db)
        candidate = repository.find_best_candidate(payload, result)
    except Exception:
        logger.exception("Failed to query learned quote rules.", extra={"quote_id": result.quote_id})
        if rollback_on_error:
            db.rollback()
        return result

    if candidate is None:
        return result
    learned_rule, match_score = candidate
    if not _origin_matches_expected_route(payload, result, learned_rule.origin, learned_rule.zone):
        return result
    if not _should_apply_learned_rule(result, learned_rule, match_score):
        return result
    if mark_used:
        repository.mark_used(learned_rule)
    return _result_from_learned_rule(payload, result, learned_rule, match_score=match_score)


def enforce_origin_matrix_safety(
    request: ZoneQuoteRequest,
    result: ZoneQuoteResult,
) -> ZoneQuoteResult:
    if result.matched_by == "origin_matrix_guard":
        return result

    postal_province = get_province_from_postal_code(request.postal_code)
    province = postal_province or result.province or request.province
    expected_origin = ORIGIN_BY_PROVINCE.get(province or "")
    actual_origin = normalize_origin(result.origin)
    crossed_matrices = "stale_origin_overridden" in result.risk_tags
    origin_mismatch = actual_origin is not None and actual_origin != expected_origin
    if expected_origin is None or (not origin_mismatch and not crossed_matrices):
        return result

    rejected_origin = result.origin
    rejected_zone = result.zone
    # ponytail: a Zone number cannot cross price matrices; stay manual until a corrected rule exists.
    return result.model_copy(
        update={
            "source_type": ZoneQuoteSourceType.MANUAL_REQUIRED,
            "confidence": 0,
            "province": province,
            "origin": None,
            "zone": None,
            "base_price_usd": None,
            "fuel_usd": None,
            "accessorials": {},
            "total_price_usd": None,
            "risk_tags": sorted(set([*result.risk_tags, "origin_matrix_mismatch"])),
            "manual_review_required": True,
            "matched_rule": (
                f"origin_matrix_guard + {province or 'unknown province'} expects {expected_origin}; "
                f"rejected {rejected_origin or 'unknown origin'} Zone {rejected_zone or 'unknown'}"
            ),
            "matched_by": "origin_matrix_guard",
            "match_trace": {
                **result.match_trace,
                "expected_origin": expected_origin,
                "postal_province": postal_province,
                "rejected_origin": rejected_origin,
                "rejected_zone": rejected_zone,
                "rejected_matched_by": result.matched_by,
                "matched_by": "origin_matrix_guard",
            },
            "sales_note": "需要人工复核始发仓和 Zone 后才能向客户发送报价。",
            "internal_note": "始发仓与 Zone 规则来源不一致，已阻止跨价格矩阵报价并转人工确认。",
        }
    )


def enforce_zone_price_switch(
    pricing_config: ZonePricingConfig,
    result: ZoneQuoteResult,
) -> ZoneQuoteResult:
    if result.origin is None or result.zone is None:
        return result
    if pricing_config.zone_price_enabled_for(result.origin, result.zone):
        return result

    previous_matched_by = result.matched_by
    previous_source_type = result.source_type.value
    return result.model_copy(
        update={
            "source_type": ZoneQuoteSourceType.MANUAL_REQUIRED,
            "confidence": 0,
            "base_price_usd": None,
            "fuel_usd": None,
            "accessorials": {},
            "total_price_usd": None,
            "risk_tags": sorted(set([*result.risk_tags, "zone_price_disabled"])),
            "manual_review_required": True,
            "matched_rule": build_zone_price_disabled_reason(
                city=result.preferred_city or result.city,
                province=result.province,
                postal_code=result.postal_code,
                origin=result.origin,
                zone=result.zone,
            ),
            "matched_by": "zone_price_disabled",
            "match_trace": {
                **result.match_trace,
                "previous_matched_by": previous_matched_by,
                "previous_source_type": previous_source_type,
                "matched_by": "zone_price_disabled",
                "zone_price_enabled": False,
            },
            "sales_note": "该分区价格已暂停自动报价，需要人工确认后才能向客户发送金额。",
            "internal_note": "该始发仓 + Zone 已在价格配置中关闭，任何自动报价来源均不得绕过。",
        }
    )


def _origin_matches_expected_route(
    request: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    origin: str | None,
    zone: int | None,
) -> bool:
    province = get_province_from_postal_code(request.postal_code) or result.province or request.province
    expected_origin = ORIGIN_BY_PROVINCE.get(province or "")
    resolved_origin = normalize_origin(origin or result.origin)
    if resolved_origin is None:
        return zone is None
    return expected_origin is None or resolved_origin == expected_origin


def record_zone_quote_side_effects(
    db: Session,
    payload: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    *,
    raw_input: str | None = None,
    extraction: dict[str, object] | None = None,
    source: str = "zone_quote",
    manual_email_config_id: int | None = None,
    manual_wecom_bot_id: int | None = None,
) -> None:
    try:
        QuoteAuditRepository(db).create_for_zone_quote(payload, result)
    except Exception:
        logger.exception("Failed to write zone quote audit log.", extra={"quote_id": result.quote_id})
        db.rollback()

    enqueue_quote_diagnostic(
        db,
        payload,
        result,
        raw_input=raw_input,
        extraction=extraction,
        source=source,
    )

    if not result.manual_review_required:
        return

    try:
        ManualQuoteTaskRepository(db).create_from_zone_quote(payload, result)
    except Exception:
        logger.exception("Failed to create manual quote task.", extra={"quote_id": result.quote_id})
        db.rollback()

    try_notification(
        "manual_required",
        lambda: notify_manual_required(
            db,
            result=result,
            request=payload,
            bot_id=manual_wecom_bot_id,
            email_config_id=manual_email_config_id,
        ),
        result.quote_id,
    )


def try_notification(label: str, callback, quote_id: str) -> None:
    try:
        callback()
    except Exception:
        logger.exception("Notification side effect failed.", extra={"label": label, "quote_id": quote_id})


try_wecom_notify = try_notification


def _result_from_learned_rule(
    request: ZoneQuoteRequest,
    original: ZoneQuoteResult,
    rule: LearnedQuoteRule,
    *,
    match_score: int,
) -> ZoneQuoteResult:
    is_corrective_override = not original.manual_review_required
    total_price = Decimal(rule.total_price_usd).quantize(Decimal("0.01"))
    base_price = Decimal(rule.base_price_usd or rule.total_price_usd).quantize(Decimal("0.01"))
    risk_tags = ["learned_quote_reused", "learned_from_manual_task"]
    risk_tags.extend(rural_fsa_risk_tags(request.postal_code))
    if is_corrective_override:
        risk_tags.extend(original.risk_tags)
        risk_tags.append("hermes_corrective_override")
    result = ZoneQuoteResult(
        quote_id=original.quote_id,
        source_type=ZoneQuoteSourceType.LEARNED_MANUAL_QUOTE,
        confidence=rule.confidence,
        postal_code=request.postal_code,
        preferred_city=original.preferred_city,
        postal_prefix=original.postal_prefix or rule.postal_prefix,
        city=original.city or rule.city or request.city,
        province=original.province or rule.province or request.province,
        origin=rule.origin or original.origin,
        zone=rule.zone if rule.zone is not None else original.zone,
        billing_pallets=rule.billing_pallets,
        pallet_breakdown=original.pallet_breakdown,
        base_price_usd=base_price,
        fuel_usd=Decimal("0.00"),
        accessorials={},
        total_price_usd=total_price,
        risk_tags=sorted(set(risk_tags)),
        manual_review_required=False,
        matched_rule=(
            f"learned_manual_quote + task {rule.source_task_id} + score {match_score} + {rule.scope} + "
            f"{rule.postal_code or rule.postal_prefix or 'unknown'} + {rule.billing_pallets} pallets"
        ),
        internal_note=(
            "已审核人工学习规则在报价时被复用；不是 AI 计算，也没有改写 Zone 价格表。"
            if is_corrective_override
            else "报价来自人工确认后的学习库，不是 AI 计算；建议运营定期复核并转入正式 Zone 价格表。"
        ),
    )
    result.sales_note = _build_learned_sales_note(request, result)
    return result


def _build_learned_sales_note(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> str:
    origin = origin_label(result.origin) or "人工确认线路"
    zone = f"（Zone {result.zone}）" if result.zone is not None else ""
    rural_confirmation_lines = (
        ["- 该地址为乡村邮编，完整地址、卡车准入及可能附加费需再次核实"]
        if RURAL_FSA_SECONDARY_CONFIRMATION_TAG in result.risk_tags
        else []
    )
    return "\n".join(
        [
            f"地址：{request.address_line or ''}".rstrip(),
            f"货物：{request.packaging_type} / {request.cbm} CBM / {request.weight_kg} KG / {request.piece_count}件",
            f"计费托数：{result.billing_pallets}托",
            f"报价：${result.total_price_usd} USD {origin}派送{zone}",
            "",
            "备注：此报价来源于此前人工确认后的学习记录，金额已由后端锁定，AI 不参与改价。",
            "- 送货到门口路边，不含其他任何操作",
            "- 如地址类型、卸货条件、复重复尺变化，费用可能需要重新确认",
            *rural_confirmation_lines,
        ]
    )


def _should_apply_learned_rule(result: ZoneQuoteResult, rule: LearnedQuoteRule, match_score: int) -> bool:
    if result.manual_review_required:
        return True
    if match_score >= 100:
        return True
    if match_score >= 90 and _has_correctable_zone_risk(result) and _learned_rule_differs_from_zone_result(result, rule):
        return True
    return False


def _has_correctable_zone_risk(result: ZoneQuoteResult) -> bool:
    correctable_tags = {
        "city_zone_fallback",
        "city_zone_prefix_family_fallback",
        "postal_family_fallback",
        "nearest_postal_prefix_fallback",
        "stale_origin_overridden",
    }
    return bool(correctable_tags.intersection(result.risk_tags))


def _learned_rule_differs_from_zone_result(result: ZoneQuoteResult, rule: LearnedQuoteRule) -> bool:
    if rule.origin and result.origin and rule.origin != result.origin:
        return True
    if rule.zone is not None and result.zone is not None and rule.zone != result.zone:
        return True
    if rule.total_price_usd is not None and result.total_price_usd is not None:
        return Decimal(rule.total_price_usd).quantize(Decimal("0.01")) != Decimal(result.total_price_usd).quantize(Decimal("0.01"))
    return False
