from __future__ import annotations

import logging

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
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


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
    record_zone_quote_side_effects(db, payload, result, manual_wecom_bot_id=wecom_bot_id)
    if notify_wecom and not result.manual_review_required:
        try_wecom_notify(
            "quote_success",
            lambda: notify_quote_success(db, result=result, request=payload, bot_id=wecom_bot_id),
            result.quote_id,
        )
    return result


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
