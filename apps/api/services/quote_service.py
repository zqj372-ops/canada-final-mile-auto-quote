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
from apps.api.services.notification_service import notify_manual_required, notify_quote_success
from packages.quote_engine.engine import QuoteEngine
from packages.quote_engine.models import QuoteCalculationRequest, QuoteResult, ShipmentInput
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_lookup import origin_label
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult, ZoneQuoteSourceType


logger = logging.getLogger(__name__)


def calculate_vendor_quote(db: Session, shipment: ShipmentInput) -> QuoteResult:
    candidate_rules = RateRuleRepository(db).list_candidate_rules(shipment)
    request = QuoteCalculationRequest(shipment=shipment, rate_rules=candidate_rules)
    return QuoteEngine().quote(request)


def calculate_zone_quote(
    db: Session,
    payload: ZoneQuoteRequest,
    *,
    notify_wecom: bool = False,
    wecom_bot_id: int | None = None,
) -> ZoneQuoteResult:
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    result = ZoneQuoteEngine(ZoneRepository(db), pricing_config=pricing_config).quote(payload)
    result = apply_learned_quote_if_available(db, payload, result)
    record_zone_quote_side_effects(db, payload, result, manual_wecom_bot_id=wecom_bot_id)
    if notify_wecom and not result.manual_review_required:
        try_wecom_notify(
            "quote_success",
            lambda: notify_quote_success(db, result=result, request=payload, bot_id=wecom_bot_id),
            result.quote_id,
        )
    return result


def apply_learned_quote_if_available(
    db: Session,
    payload: ZoneQuoteRequest,
    result: ZoneQuoteResult,
) -> ZoneQuoteResult:
    if not result.manual_review_required:
        return result

    try:
        learned_rule = LearnedQuoteRuleRepository(db).find_match(payload, result)
    except Exception:
        logger.exception("Failed to query learned quote rules.", extra={"quote_id": result.quote_id})
        db.rollback()
        return result

    if learned_rule is None:
        return result
    return _result_from_learned_rule(payload, result, learned_rule)


def record_zone_quote_side_effects(
    db: Session,
    payload: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    *,
    manual_wecom_bot_id: int | None = None,
) -> None:
    try:
        QuoteAuditRepository(db).create_for_zone_quote(payload, result)
    except Exception:
        logger.exception("Failed to write zone quote audit log.", extra={"quote_id": result.quote_id})
        db.rollback()

    if not result.manual_review_required:
        return

    try:
        ManualQuoteTaskRepository(db).create_from_zone_quote(payload, result)
    except Exception:
        logger.exception("Failed to create manual quote task.", extra={"quote_id": result.quote_id})
        db.rollback()

    try_wecom_notify(
        "manual_required",
        lambda: notify_manual_required(db, result=result, request=payload, bot_id=manual_wecom_bot_id),
        result.quote_id,
    )


def try_wecom_notify(label: str, callback, quote_id: str) -> None:
    try:
        callback()
    except Exception:
        logger.exception("WeCom notification side effect failed.", extra={"label": label, "quote_id": quote_id})


def _result_from_learned_rule(
    request: ZoneQuoteRequest,
    original: ZoneQuoteResult,
    rule: LearnedQuoteRule,
) -> ZoneQuoteResult:
    total_price = Decimal(rule.total_price_usd).quantize(Decimal("0.01"))
    base_price = Decimal(rule.base_price_usd or rule.total_price_usd).quantize(Decimal("0.01"))
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
        risk_tags=["learned_quote_reused", "learned_from_manual_task"],
        manual_review_required=False,
        matched_rule=(
            f"learned_manual_quote + task {rule.source_task_id} + {rule.scope} + "
            f"{rule.postal_prefix or rule.postal_code or 'unknown'} + {rule.billing_pallets} pallets"
        ),
        internal_note=(
            "报价来自人工确认后的学习库，不是 AI 计算；建议运营定期复核并转入正式 Zone 价格表。"
        ),
    )
    result.sales_note = _build_learned_sales_note(request, result)
    return result


def _build_learned_sales_note(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> str:
    origin = origin_label(result.origin) or "人工确认线路"
    zone = f"（Zone {result.zone}）" if result.zone is not None else ""
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
        ]
    )
