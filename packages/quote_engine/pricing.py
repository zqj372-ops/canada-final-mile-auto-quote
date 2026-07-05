from decimal import Decimal, ROUND_HALF_UP

from packages.quote_engine.models import MatchResult, QuoteResult, ShipmentInput, SourceType


MONEY = Decimal("0.01")
PERCENT = Decimal("0.0001")


def money(value: Decimal) -> Decimal:
    return value.quantize(MONEY, rounding=ROUND_HALF_UP)


def percent(value: Decimal) -> Decimal:
    return value.quantize(PERCENT, rounding=ROUND_HALF_UP)


def calculate_quote(shipment: ShipmentInput, match: MatchResult) -> QuoteResult:
    if match.source_type == SourceType.MANUAL_REQUIRED or match.rule is None:
        return QuoteResult(
            source_type=SourceType.MANUAL_REQUIRED,
            confidence=0,
            matched_rule=match.matched_rule,
            cost_breakdown={},
            risk_tags=build_risk_tags(shipment),
            manual_review_required=True,
            sales_note="Manual review required before sharing a price.",
            internal_note="No deterministic rule matched. Do not invent a quote.",
        )

    rule = match.rule
    base_cost = money(rule.base_cost_cad)
    fuel = money(base_cost * rule.fuel_percent / Decimal("100"))
    appointment_fee = rule.appointment_fee_cad if shipment.requires_appointment else Decimal("0")
    liftgate_fee = rule.liftgate_fee_cad if shipment.requires_liftgate else Decimal("0")
    residential_fee = rule.residential_fee_cad if shipment.is_residential else Decimal("0")
    limited_access_fee = rule.limited_access_fee_cad if shipment.limited_access else Decimal("0")
    remote_fee = rule.remote_fee_cad if shipment.remote_area else Decimal("0")

    breakdown = {
        "base_cost": money(base_cost),
        "fuel": money(fuel),
        "appointment_fee": money(appointment_fee),
        "liftgate_fee": money(liftgate_fee),
        "residential_fee": money(residential_fee),
        "limited_access_fee": money(limited_access_fee),
        "remote_fee": money(remote_fee),
    }
    internal_cost = money(sum(breakdown.values(), Decimal("0")))
    suggested_selling = money(internal_cost / (Decimal("1") - shipment.target_margin_percent))
    margin = money(suggested_selling - internal_cost)
    margin_percent = percent(margin / suggested_selling) if suggested_selling else Decimal("0")

    return QuoteResult(
        source_type=match.source_type,
        confidence=match.confidence,
        matched_rule=match.matched_rule,
        internal_cost_cad=internal_cost,
        suggested_selling_price_cad=suggested_selling,
        margin_cad=margin,
        margin_percent=margin_percent,
        cost_breakdown=breakdown,
        risk_tags=build_risk_tags(shipment),
        manual_review_required=False,
        sales_note="Price is calculated from a deterministic rate rule.",
        internal_note=f"Matched rule {rule.rule_id}. AI may explain but must not change price.",
    )


def build_risk_tags(shipment: ShipmentInput) -> list[str]:
    tags: list[str] = []
    if shipment.dock_available is None:
        tags.append("dock_unknown")
    elif not shipment.dock_available:
        tags.append("dock_unavailable")
    if shipment.requires_appointment:
        tags.append("appointment_required")
    if shipment.requires_liftgate:
        tags.append("liftgate_required")
    if shipment.is_residential:
        tags.append("residential")
    if shipment.limited_access:
        tags.append("limited_access")
    if shipment.remote_area:
        tags.append("remote_area")
    return tags

