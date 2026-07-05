from dataclasses import dataclass
from decimal import Decimal
import re

from packages.address_normalizer import extract_fsa
from packages.quote_engine.models import MatchResult, RateRule, ShipmentInput, SourceType


PRIORITY = [
    SourceType.HISTORY_EXACT_ADDRESS,
    SourceType.POSTAL_CODE,
    SourceType.FSA,
    SourceType.CITY,
    SourceType.RATE_CARD,
    SourceType.DISTANCE_FALLBACK,
]

CONFIDENCE = {
    SourceType.HISTORY_EXACT_ADDRESS: 95,
    SourceType.POSTAL_CODE: 90,
    SourceType.FSA: 80,
    SourceType.CITY: 65,
    SourceType.RATE_CARD: 50,
    SourceType.DISTANCE_FALLBACK: 35,
    SourceType.MANUAL_REQUIRED: 0,
}


@dataclass(frozen=True)
class ShipmentMatchContext:
    address_fingerprint: str | None
    postal_code: str | None
    fsa: str | None
    city: str | None
    province: str | None
    origin_warehouse: str | None
    pallet_count: int
    weight_kg: Decimal | None


def fingerprint_address(value: str | None) -> str | None:
    if not value:
        return None
    compact = re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
    return re.sub(r"\s+", " ", compact) or None


def build_match_context(shipment: ShipmentInput) -> ShipmentMatchContext:
    return ShipmentMatchContext(
        address_fingerprint=fingerprint_address(shipment.address_line),
        postal_code=shipment.postal_code,
        fsa=extract_fsa(shipment.postal_code),
        city=shipment.city,
        province=shipment.province,
        origin_warehouse=shipment.origin_warehouse,
        pallet_count=shipment.pallet_count,
        weight_kg=shipment.weight_kg,
    )


def find_best_rule(shipment: ShipmentInput, rate_rules: list[RateRule]) -> MatchResult:
    context = build_match_context(shipment)
    active_rules = [rule for rule in rate_rules if rule.status.lower() == "active"]

    for source_type in PRIORITY:
        for rule in active_rules:
            if rule.source_type == source_type and rule_matches_context(rule, context):
                return MatchResult(
                    source_type=source_type,
                    confidence=CONFIDENCE[source_type],
                    matched_rule=describe_match(rule, context),
                    rule=rule,
                )

    return MatchResult(
        source_type=SourceType.MANUAL_REQUIRED,
        confidence=0,
        matched_rule="No deterministic rate rule matched. Manual review required.",
        rule=None,
    )


def rule_matches_context(rule: RateRule, context: ShipmentMatchContext) -> bool:
    if not (rule.pallet_min <= context.pallet_count <= rule.pallet_max):
        return False
    if not weight_matches(rule, context):
        return False
    if rule.origin_warehouse:
        if not context.origin_warehouse:
            return False
        if rule.origin_warehouse.lower() != context.origin_warehouse.lower():
            return False
    if not province_matches(rule, context):
        return False

    if rule.source_type == SourceType.HISTORY_EXACT_ADDRESS:
        return bool(
            rule.address_fingerprint
            and context.address_fingerprint
            and rule.address_fingerprint == context.address_fingerprint
        )
    if rule.source_type == SourceType.POSTAL_CODE:
        return bool(rule.postal_code and context.postal_code and rule.postal_code == context.postal_code)
    if rule.source_type == SourceType.FSA:
        return bool(rule.fsa and context.fsa and rule.fsa == context.fsa)
    if rule.source_type == SourceType.CITY:
        return bool(rule.city and context.city and rule.city == context.city and rule.province == context.province)
    if rule.source_type == SourceType.RATE_CARD:
        return bool(rule.vendor_name)
    if rule.source_type == SourceType.DISTANCE_FALLBACK:
        return False
    return False


def weight_matches(rule: RateRule, context: ShipmentMatchContext) -> bool:
    if rule.weight_min_kg is None and rule.weight_max_kg is None:
        return True
    if context.weight_kg is None:
        return False
    if rule.weight_min_kg is not None and context.weight_kg < rule.weight_min_kg:
        return False
    if rule.weight_max_kg is not None and context.weight_kg > rule.weight_max_kg:
        return False
    return True


def province_matches(rule: RateRule, context: ShipmentMatchContext) -> bool:
    if not rule.province:
        return True
    if rule.source_type == SourceType.HISTORY_EXACT_ADDRESS and not context.province:
        return True
    return bool(context.province and rule.province == context.province)


def describe_match(rule: RateRule, context: ShipmentMatchContext) -> str:
    parts = [rule.source_type.value]
    if rule.origin_warehouse or context.origin_warehouse:
        parts.append(rule.origin_warehouse or context.origin_warehouse or "")
    if rule.province or context.province:
        parts.append(rule.province or context.province or "")
    if rule.city or context.city:
        parts.append(rule.city or context.city or "")
    if rule.postal_code or rule.fsa or context.postal_code or context.fsa:
        parts.append(rule.postal_code or rule.fsa or context.postal_code or context.fsa or "")
    parts.append(f"{context.pallet_count} pallets")
    return " + ".join(part for part in parts if part)
