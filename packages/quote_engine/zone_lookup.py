from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.zone_models import PostalCodeCityRecord, ZoneLookupDecision, ZoneLookupRuleRecord


PROVINCE_BY_POSTAL_INITIAL = {
    "A": "NL",
    "B": "NS",
    "C": "PE",
    "E": "NB",
    "G": "QC",
    "H": "QC",
    "J": "QC",
    "K": "ON",
    "L": "ON",
    "M": "ON",
    "N": "ON",
    "P": "ON",
    "R": "MB",
    "S": "SK",
    "T": "AB",
    "V": "BC",
    "X": "NT",
    "Y": "YT",
}

ORIGIN_ALIASES = {
    "toronto": "toronto",
    "多伦多": "toronto",
    "yyz": "toronto",
    "calgary": "calgary",
    "卡尔加里": "calgary",
    "yyc": "calgary",
    "vancouver": "calgary",
}

ORIGIN_LABELS = {
    "toronto": "多伦多",
    "calgary": "卡尔加里",
}


def normalize_origin(value: str | None) -> str | None:
    if not value:
        return None
    key = value.strip().lower()
    return ORIGIN_ALIASES.get(key, key)


def origin_label(value: str | None) -> str:
    normalized = normalize_origin(value)
    return ORIGIN_LABELS.get(normalized or "", value or "")


def get_province_from_postal_code(postal_code: str | None) -> str | None:
    normalized = normalize_postal_code(postal_code)
    if not normalized:
        return None
    return PROVINCE_BY_POSTAL_INITIAL.get(normalized[0])


def lookup_preferred_city_by_postal_code(
    postal_code: str,
    records: Mapping[str, PostalCodeCityRecord | str] | Sequence[PostalCodeCityRecord],
) -> PostalCodeCityRecord | None:
    normalized = normalize_postal_code(postal_code)
    if not normalized:
        return None

    if isinstance(records, Mapping):
        compact = normalized.replace(" ", "")
        value = records.get(normalized) or records.get(compact)
        if isinstance(value, PostalCodeCityRecord):
            return value
        if isinstance(value, str):
            return PostalCodeCityRecord(
                postal_code=normalized,
                preferred_city=normalize_city(value) or value,
                province=get_province_from_postal_code(normalized),
            )
        return None

    for record in records:
        if record.postal_code == normalized:
            return record
    return None


def lookup_zone_by_postal_prefix_city_province(
    postal_prefix: str,
    city: str | None,
    province: str | None,
    rules: Sequence[ZoneLookupRuleRecord],
) -> ZoneLookupDecision:
    prefix = _normalize_prefix(postal_prefix)
    prefix_rules = [rule for rule in rules if _normalize_prefix(rule.postal_prefix) == prefix]
    if not prefix_rules:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"No zone rule found for postal prefix {prefix}.",
            risk_tags=("zone_not_found",),
        )

    if detect_split_record_conflict(prefix_rules, city, province):
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"Split-record conflict for {prefix}; city/province did not resolve a unique zone.",
            risk_tags=("split_record_conflict",),
        )

    filtered = _filter_rules(prefix_rules, city, province)
    if not filtered:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"No zone rule matched {prefix} + {city or 'unknown city'} + {province or 'unknown province'}.",
            risk_tags=("zone_not_found",),
        )

    groups = _unique_groups(filtered)
    if len(groups) != 1:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"Multiple zone rules matched {prefix}; manual confirmation required.",
            risk_tags=("split_record_conflict",),
        )

    original = filtered[0]
    rule, risk_tags = _apply_origin_overrides(original)
    return ZoneLookupDecision(
        manual_required=False,
        matched_rule=f"{prefix} + {rule.city.title()} + {rule.province} -> {rule.origin} Zone {rule.zone}",
        rule=rule,
        origin=rule.origin,
        zone=rule.zone,
        confidence=85,
        risk_tags=tuple(risk_tags),
    )


def detect_split_record_conflict(
    rules: Sequence[ZoneLookupRuleRecord],
    city: str | None = None,
    province: str | None = None,
) -> bool:
    if not rules:
        return False
    filtered = _filter_rules(rules, city, province)
    if not filtered:
        return len(_unique_groups(rules)) > 1
    return len(_unique_groups(filtered)) > 1


def _filter_rules(
    rules: Sequence[ZoneLookupRuleRecord],
    city: str | None,
    province: str | None,
) -> list[ZoneLookupRuleRecord]:
    normalized_city = _normalize_city_for_lookup(city)
    normalized_province = normalize_province(province)
    filtered = list(rules)
    if normalized_province:
        filtered = [rule for rule in filtered if normalize_province(rule.province) == normalized_province]
    if normalized_city:
        filtered = [rule for rule in filtered if _normalize_city_for_lookup(rule.city) == normalized_city]
    return filtered


def _unique_groups(rules: Sequence[ZoneLookupRuleRecord]) -> set[tuple[int, str | None, str]]:
    groups = set()
    for rule in rules:
        overridden, _ = _apply_origin_overrides(rule)
        groups.add((overridden.zone, normalize_origin(overridden.origin), normalize_province(overridden.province) or ""))
    return groups


def _apply_origin_overrides(rule: ZoneLookupRuleRecord) -> tuple[ZoneLookupRuleRecord, list[str]]:
    risk_tags: list[str] = []
    origin = normalize_origin(rule.origin)
    if normalize_province(rule.province) == "BC" and origin != "calgary":
        origin = "calgary"
        risk_tags.append("stale_origin_overridden")
    return replace(rule, origin=origin or rule.origin), risk_tags


def _normalize_prefix(value: str | None) -> str:
    if not value:
        return ""
    extracted = extract_fsa(value)
    return extracted or value.strip().upper().replace(" ", "")[:3]


def _normalize_city_for_lookup(value: str | None) -> str | None:
    if not value:
        return None
    normalized = normalize_city(value) or value
    return normalized.upper()


def record_from_mapping(row: Mapping[str, Any]) -> ZoneLookupRuleRecord:
    return ZoneLookupRuleRecord(
        postal_prefix=str(row["postal_prefix"]).upper(),
        city=str(row["city"]).upper(),
        province=str(row["province"]).upper(),
        origin=normalize_origin(str(row["origin"])) or str(row["origin"]),
        zone=int(row["zone"]),
        match_level=str(row.get("match_level") or "") or None,
        note=str(row.get("note") or "") or None,
    )

