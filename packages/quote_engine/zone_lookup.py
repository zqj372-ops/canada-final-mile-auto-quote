from collections.abc import Mapping, Sequence
from dataclasses import replace
from typing import Any

from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.zone_models import (
    CityAliasRecord,
    PostalCodeCityRecord,
    PostalZoneOverrideRecord,
    ZoneLookupDecision,
    ZoneLookupRuleRecord,
)


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

ORIGIN_BY_PROVINCE = {
    "BC": "calgary",
    "AB": "calgary",
    "SK": "calgary",
    "MB": "calgary",
    "ON": "toronto",
    "QC": "toronto",
    "NB": "toronto",
    "NS": "toronto",
    "PE": "toronto",
    "NL": "toronto",
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
    return lookup_zone(
        postal_code=None,
        postal_prefix=postal_prefix,
        input_city=city,
        preferred_city=None,
        province=province,
        rules=rules,
        aliases=(),
        override=None,
    )


def lookup_zone(
    *,
    postal_code: str | None,
    postal_prefix: str,
    input_city: str | None,
    preferred_city: str | None,
    province: str | None,
    rules: Sequence[ZoneLookupRuleRecord],
    aliases: Sequence[CityAliasRecord],
    override: PostalZoneOverrideRecord | None = None,
) -> ZoneLookupDecision:
    prefix = _normalize_prefix(postal_prefix)
    normalized_postal_code = normalize_postal_code(postal_code)
    normalized_province = normalize_province(province) or get_province_from_postal_code(normalized_postal_code)
    active_rules = [rule for rule in rules if rule.active]
    prefix_rules = [rule for rule in active_rules if _normalize_prefix(rule.postal_prefix) == prefix]
    alias_map = _alias_map(aliases, normalized_province)
    city_candidates, alias_used = _city_candidates(input_city, preferred_city, alias_map)
    trace: dict[str, object] = {
        "postal_code": normalized_postal_code,
        "fsa": prefix,
        "input_city": input_city,
        "preferred_city": preferred_city,
        "province": normalized_province,
        "canonical_city_candidates": city_candidates,
        "candidate_count": len(prefix_rules),
    }

    if override is not None:
        rule = ZoneLookupRuleRecord(
            postal_prefix=override.postal_prefix,
            city=override.canonical_city or input_city or preferred_city or "",
            province=override.province,
            origin=override.origin,
            zone=override.zone,
            canonical_city=override.canonical_city,
            match_level="postal_zone_override",
            note=override.note,
        )
        rule, risk_tags = _apply_origin_overrides(rule)
        trace.update(
            {
                "matched_by": "postal_code_override",
                "candidate_count": 1,
                "override_source": override.source,
            }
        )
        return ZoneLookupDecision(
            manual_required=False,
            matched_rule=(
                f"postal_code_override + {override.postal_code} -> {rule.origin} Zone {rule.zone}"
            ),
            rule=rule,
            origin=rule.origin,
            zone=rule.zone,
            confidence=override.confidence,
            risk_tags=tuple(risk_tags),
            matched_by="postal_code_override",
            candidate_count=1,
            match_trace=trace,
        )

    if not prefix_rules:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"未命中邮编前缀 {prefix} 的 Zone 分区规则。",
            risk_tags=("zone_not_found",),
            matched_by="zone_not_found",
            candidate_count=0,
            match_trace=trace,
        )

    province_rules = _filter_rules_by_province(prefix_rules, normalized_province)
    if not province_rules:
        trace.update({"province_filtered_count": 0})
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix} + {normalized_province or '未知省份'} 未匹配到 Zone 规则。",
            risk_tags=("zone_not_found",),
            matched_by="province_not_found",
            candidate_count=len(prefix_rules),
            match_trace=trace,
        )

    trace["province_filtered_count"] = len(province_rules)
    single_group = _single_group_decision(
        province_rules,
        prefix=prefix,
        matched_by="fsa_single_zone",
        confidence=90,
        trace=trace,
    )
    if single_group is not None:
        return single_group

    city_filtered = _filter_rules_by_canonical_city(province_rules, city_candidates, alias_map)
    trace["city_filtered_count"] = len(city_filtered)
    if city_filtered:
        groups = _unique_groups(city_filtered)
        if len(groups) == 1:
            original = _choose_best_rule(city_filtered)
            rule, risk_tags = _apply_origin_overrides(original)
            matched_by = "city_alias" if alias_used else "canonical_city"
            trace.update(
                {
                    "matched_by": matched_by,
                    "matched_rule_city": rule.canonical_city or rule.city,
                    "candidate_count": len(city_filtered),
                }
            )
            return ZoneLookupDecision(
                manual_required=False,
                matched_rule=f"{matched_by} + {prefix} + {rule.province} + {rule.city} -> {rule.origin} Zone {rule.zone}",
                rule=rule,
                origin=rule.origin,
                zone=rule.zone,
                confidence=88 if alias_used else 86,
                risk_tags=tuple(risk_tags),
                matched_by=matched_by,
                candidate_count=len(city_filtered),
                match_trace=trace,
            )
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix} + {input_city or preferred_city or '未知城市'} 匹配到多个 Zone 规则，需要人工确认。",
            risk_tags=("split_record_conflict",),
            matched_by="split_record_conflict",
            candidate_count=len(city_filtered),
            match_trace={
                **trace,
                "matched_by": "split_record_conflict",
                "unique_group_count": len(groups),
            },
        )

    if city_candidates:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=(
                f"邮编前缀 {prefix} + {input_city or preferred_city or '未知城市'} + "
                f"{normalized_province or '未知省份'} 未唯一匹配到 Zone 规则。"
            ),
            risk_tags=("zone_not_found",),
            matched_by="city_not_found",
            candidate_count=len(province_rules),
            match_trace=trace,
        )

    return ZoneLookupDecision(
        manual_required=True,
        matched_rule=f"邮编前缀 {prefix} 匹配到多个 Zone 规则，需要人工确认。",
        risk_tags=("split_record_conflict",),
        matched_by="split_record_conflict",
        candidate_count=len(province_rules),
        match_trace=trace,
    )


def lookup_zone_by_city_province(
    *,
    city: str | None,
    province: str | None,
    rules: Sequence[ZoneLookupRuleRecord],
    requested_postal_prefix: str | None = None,
) -> ZoneLookupDecision:
    normalized_city = _normalize_city_for_lookup(city)
    normalized_province = normalize_province(province)
    prefix = _normalize_prefix(requested_postal_prefix)
    if not normalized_city or not normalized_province:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix or '未知'} 未命中，且城市/省份不足以匹配 Zone。",
            risk_tags=("zone_not_found",),
            matched_by="city_fallback_missing_context",
            candidate_count=0,
            match_trace={
                "fsa": prefix,
                "input_city": city,
                "province": normalized_province,
                "matched_by": "city_fallback_missing_context",
            },
        )

    filtered = _filter_rules(rules, city, province)
    if not filtered:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix or '未知'} 未命中，城市 {city} + {province} 也未匹配到 Zone 规则。",
            risk_tags=("zone_not_found",),
            matched_by="city_fallback_not_found",
            candidate_count=len(rules),
            match_trace={
                "fsa": prefix,
                "input_city": city,
                "province": normalized_province,
                "candidate_count": len(rules),
                "city_filtered_count": 0,
                "matched_by": "city_fallback_not_found",
            },
        )

    expected_origin = ORIGIN_BY_PROVINCE.get(normalized_province)
    if expected_origin and not any(normalize_origin(rule.origin) == expected_origin for rule in filtered):
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=(
                f"城市 {city} + {province} 只有不符合省份始发仓 {expected_origin} 的旧 Zone 锚点，"
                "需要人工确认或补充可信锚点。"
            ),
            risk_tags=("zone_not_found",),
            matched_by="city_fallback_expected_origin_not_found",
            candidate_count=len(filtered),
            match_trace={
                "fsa": prefix,
                "input_city": city,
                "province": normalized_province,
                "candidate_count": len(filtered),
                "expected_origin": expected_origin,
                "matched_by": "city_fallback_expected_origin_not_found",
            },
        )

    match_rules, origin_preference_applied = _prefer_expected_origin_rules(filtered, expected_origin)
    prefix_family_label: str | None = None
    narrowed = _select_unique_prefix_family_rules(match_rules, prefix)
    if narrowed is not None:
        narrowed_rules, prefix_family_label = narrowed
        if prefix_family_label or len(narrowed_rules) < len(match_rules):
            match_rules = narrowed_rules
    groups = _unique_groups(match_rules)
    if len(groups) != 1:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"城市 {city} + {province} 匹配到多个 Zone 规则，需要人工确认。",
            risk_tags=("split_record_conflict",),
            matched_by="city_fallback_split_record_conflict",
            candidate_count=len(match_rules),
            match_trace={
                "fsa": prefix,
                "input_city": city,
                "province": normalized_province,
                "candidate_count": len(match_rules),
                "city_filtered_count": len(filtered),
                "expected_origin": expected_origin,
                "origin_preference_applied": origin_preference_applied,
                "unique_group_count": len(groups),
                "matched_by": "city_fallback_split_record_conflict",
            },
        )

    original = _choose_best_rule(match_rules)
    rule, risk_tags = _apply_origin_overrides(original)
    fallback_detail = (
        f"，按同邮编族 {prefix_family_label} 缩小城市分区"
        if prefix_family_label
        else "，使用城市分区"
    )
    result_risk_tags = [*risk_tags, "city_zone_fallback"]
    if prefix_family_label:
        result_risk_tags.append("city_zone_prefix_family_fallback")
    return ZoneLookupDecision(
        manual_required=False,
        matched_rule=(
            f"city_fallback + {city} + {rule.province} -> {rule.origin} Zone {rule.zone}"
            f"（邮编前缀 {prefix or '未知'} 未命中{fallback_detail}）"
        ),
        rule=rule,
        origin=rule.origin,
        zone=rule.zone,
        confidence=70,
        risk_tags=tuple(result_risk_tags),
        matched_by="city_zone_fallback",
        candidate_count=len(match_rules),
        match_trace={
            "fsa": prefix,
            "input_city": city,
            "province": normalized_province,
            "candidate_count": len(match_rules),
            "city_filtered_count": len(filtered),
            "expected_origin": expected_origin,
            "origin_preference_applied": origin_preference_applied,
            "prefix_family": prefix_family_label,
            "matched_by": "city_zone_fallback",
        },
    )


def lookup_zone_by_postal_family_province(
    *,
    postal_prefix: str | None,
    province: str | None,
    rules: Sequence[ZoneLookupRuleRecord],
) -> ZoneLookupDecision:
    prefix = _normalize_prefix(postal_prefix)
    normalized_province = normalize_province(province)
    expected_origin = ORIGIN_BY_PROVINCE.get(normalized_province or "")
    if not prefix or not normalized_province:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix or '未知'} 未命中，且省份不足以做邮编族模糊匹配。",
            risk_tags=("zone_not_found",),
            matched_by="postal_family_missing_context",
            candidate_count=0,
            match_trace={
                "fsa": prefix,
                "province": normalized_province,
                "matched_by": "postal_family_missing_context",
            },
        )

    family = prefix[:2] if len(prefix) >= 2 else prefix[:1]
    active_rules = [rule for rule in rules if rule.active]
    province_rules = _filter_rules_by_province(active_rules, normalized_province)
    family_rules = [rule for rule in province_rules if _normalize_prefix(rule.postal_prefix).startswith(family)]
    if not family_rules:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix} 未命中，且 {normalized_province} 没有 {family}* 邮编族锚点。",
            risk_tags=("zone_not_found",),
            matched_by="postal_family_not_found",
            candidate_count=len(province_rules),
            match_trace={
                "fsa": prefix,
                "province": normalized_province,
                "family": f"{family}*",
                "candidate_count": len(province_rules),
                "matched_by": "postal_family_not_found",
            },
        )

    expected_origin_rules = (
        [rule for rule in family_rules if normalize_origin(rule.origin) == expected_origin]
        if expected_origin
        else family_rules
    )
    if not expected_origin_rules:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=(
                f"邮编前缀 {prefix} 未命中，{family}* 邮编族没有符合 "
                f"{normalized_province} 始发仓 {expected_origin or '未知'} 的可靠锚点。"
            ),
            risk_tags=("zone_not_found",),
            matched_by="postal_family_expected_origin_not_found",
            candidate_count=len(family_rules),
            match_trace={
                "fsa": prefix,
                "province": normalized_province,
                "family": f"{family}*",
                "candidate_count": len(family_rules),
                "expected_origin": expected_origin,
                "matched_by": "postal_family_expected_origin_not_found",
            },
        )

    nearest_rules, nearest_distance = _nearest_prefix_rules(expected_origin_rules, prefix)
    groups = _unique_groups(nearest_rules)
    if len(groups) != 1:
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=f"邮编前缀 {prefix} 未命中，{family}* 最近邮编族锚点不唯一，需要人工确认。",
            risk_tags=("split_record_conflict",),
            matched_by="postal_family_split_record_conflict",
            candidate_count=len(nearest_rules),
            match_trace={
                "fsa": prefix,
                "province": normalized_province,
                "family": f"{family}*",
                "candidate_count": len(nearest_rules),
                "family_candidate_count": len(family_rules),
                "nearest_distance": nearest_distance,
                "nearest_prefixes": sorted({_normalize_prefix(rule.postal_prefix) for rule in nearest_rules}),
                "unique_group_count": len(groups),
                "expected_origin": expected_origin,
                "matched_by": "postal_family_split_record_conflict",
            },
        )

    original = _choose_best_rule(nearest_rules)
    rule, risk_tags = _apply_origin_overrides(original)
    nearest_prefix = _normalize_prefix(rule.postal_prefix)
    result_risk_tags = [*risk_tags, "postal_family_fallback", "nearest_postal_prefix_fallback"]
    return ZoneLookupDecision(
        manual_required=False,
        matched_rule=(
            f"postal_family_fallback + {prefix} + {normalized_province} + nearest {nearest_prefix} "
            f"-> {rule.origin} Zone {rule.zone}"
        ),
        rule=rule,
        origin=rule.origin,
        zone=rule.zone,
        confidence=62,
        risk_tags=tuple(result_risk_tags),
        matched_by="postal_family_fallback",
        candidate_count=len(nearest_rules),
        match_trace={
            "fsa": prefix,
            "province": normalized_province,
            "family": f"{family}*",
            "candidate_count": len(nearest_rules),
            "family_candidate_count": len(family_rules),
            "nearest_distance": nearest_distance,
            "nearest_prefixes": sorted({_normalize_prefix(rule.postal_prefix) for rule in nearest_rules}),
            "expected_origin": expected_origin,
            "matched_by": "postal_family_fallback",
        },
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
    alias_map: dict[str, str] = {}
    normalized_city = _normalize_city_for_lookup(city)
    normalized_province = normalize_province(province)
    filtered = _filter_rules_by_province([rule for rule in rules if rule.active], normalized_province)
    if normalized_city:
        filtered = _filter_rules_by_canonical_city(filtered, [normalized_city], alias_map)
    return filtered


def _filter_rules_by_province(
    rules: Sequence[ZoneLookupRuleRecord],
    normalized_province: str | None,
) -> list[ZoneLookupRuleRecord]:
    if not normalized_province:
        return list(rules)
    return [rule for rule in rules if normalize_province(rule.province) == normalized_province]


def _filter_rules_by_canonical_city(
    rules: Sequence[ZoneLookupRuleRecord],
    city_candidates: Sequence[str],
    alias_map: Mapping[str, str],
) -> list[ZoneLookupRuleRecord]:
    if not city_candidates:
        return []
    targets = {candidate for candidate in city_candidates if candidate}
    return [rule for rule in rules if _rule_city_for_lookup(rule, alias_map) in targets]


def _unique_groups(rules: Sequence[ZoneLookupRuleRecord]) -> set[tuple[int, str | None, str]]:
    groups = set()
    for rule in rules:
        overridden, _ = _apply_origin_overrides(rule)
        groups.add((overridden.zone, normalize_origin(overridden.origin), normalize_province(overridden.province) or ""))
    return groups


def _single_group_decision(
    rules: Sequence[ZoneLookupRuleRecord],
    *,
    prefix: str,
    matched_by: str,
    confidence: int,
    trace: dict[str, object],
) -> ZoneLookupDecision | None:
    groups = _unique_groups(rules)
    if len(groups) != 1:
        return None
    original = _choose_best_rule(rules)
    rule, risk_tags = _apply_origin_overrides(original)
    trace.update(
        {
            "matched_by": matched_by,
            "candidate_count": len(rules),
            "matched_rule_city": rule.canonical_city or rule.city,
        }
    )
    return ZoneLookupDecision(
        manual_required=False,
        matched_rule=f"{matched_by} + {prefix} + {rule.province} -> {rule.origin} Zone {rule.zone}",
        rule=rule,
        origin=rule.origin,
        zone=rule.zone,
        confidence=confidence,
        risk_tags=tuple(risk_tags),
        matched_by=matched_by,
        candidate_count=len(rules),
        match_trace=trace,
    )


def _choose_best_rule(rules: Sequence[ZoneLookupRuleRecord]) -> ZoneLookupRuleRecord:
    return sorted(rules, key=lambda rule: (rule.priority, _normalize_prefix(rule.postal_prefix), rule.city))[0]


def _alias_map(
    aliases: Sequence[CityAliasRecord],
    province: str | None,
) -> dict[str, str]:
    normalized_province = normalize_province(province)
    mapped: dict[str, str] = {}
    for alias in aliases:
        if normalized_province and normalize_province(alias.province) != normalized_province:
            continue
        alias_city = _normalize_city_for_lookup(alias.alias_city)
        canonical_city = _normalize_city_for_lookup(alias.canonical_city)
        if alias_city and canonical_city:
            mapped[alias_city] = canonical_city
            mapped.setdefault(canonical_city, canonical_city)
    return mapped


def _city_candidates(
    input_city: str | None,
    preferred_city: str | None,
    alias_map: Mapping[str, str],
) -> tuple[list[str], bool]:
    candidates: list[str] = []
    alias_used = False
    for value in (input_city, preferred_city):
        normalized = _normalize_city_for_lookup(value)
        if not normalized:
            continue
        canonical = alias_map.get(normalized, normalized)
        if canonical != normalized:
            alias_used = True
        if canonical not in candidates:
            candidates.append(canonical)
        if normalized not in candidates:
            candidates.append(normalized)
    return candidates, alias_used


def _rule_city_for_lookup(
    rule: ZoneLookupRuleRecord,
    alias_map: Mapping[str, str],
) -> str | None:
    canonical_city = _normalize_city_for_lookup(rule.canonical_city)
    if canonical_city:
        return alias_map.get(canonical_city, canonical_city)
    city = _normalize_city_for_lookup(rule.city)
    if city:
        return alias_map.get(city, city)
    return None


def _select_unique_prefix_family_rules(
    rules: Sequence[ZoneLookupRuleRecord],
    requested_prefix: str,
) -> tuple[list[ZoneLookupRuleRecord], str | None] | None:
    if not requested_prefix:
        return None

    exact = [rule for rule in rules if _normalize_prefix(rule.postal_prefix) == requested_prefix]
    if exact and len(_unique_groups(exact)) == 1:
        return exact, None

    for family_length in (2, 1):
        if len(requested_prefix) < family_length:
            continue
        family = requested_prefix[:family_length]
        narrowed = [rule for rule in rules if _normalize_prefix(rule.postal_prefix).startswith(family)]
        if narrowed and len(_unique_groups(narrowed)) == 1:
            return narrowed, f"{family}*"

    return None


def _prefer_expected_origin_rules(
    rules: Sequence[ZoneLookupRuleRecord],
    expected_origin: str | None,
) -> tuple[list[ZoneLookupRuleRecord], bool]:
    if not expected_origin:
        return list(rules), False
    preferred = [rule for rule in rules if normalize_origin(rule.origin) == expected_origin]
    if not preferred:
        return list(rules), False
    return preferred, len(preferred) != len(rules)


def _nearest_prefix_rules(
    rules: Sequence[ZoneLookupRuleRecord],
    requested_prefix: str,
) -> tuple[list[ZoneLookupRuleRecord], int | None]:
    distances = [
        (_prefix_distance(_normalize_prefix(rule.postal_prefix), requested_prefix), rule)
        for rule in rules
    ]
    finite_distances = [(distance, rule) for distance, rule in distances if distance is not None]
    if not finite_distances:
        return list(rules), None
    nearest_distance = min(distance for distance, _ in finite_distances)
    return [rule for distance, rule in finite_distances if distance == nearest_distance], nearest_distance


def _prefix_distance(candidate: str, requested: str) -> int | None:
    if not candidate or not requested:
        return None
    shared_length = min(len(candidate), len(requested))
    if shared_length >= 2 and candidate[:2] != requested[:2]:
        return None
    if shared_length >= 3:
        return abs(_prefix_char_rank(candidate[2]) - _prefix_char_rank(requested[2]))
    return abs(len(candidate) - len(requested))


def _prefix_char_rank(value: str) -> int:
    if value.isdigit():
        return ord(value) - ord("0")
    return 10 + ord(value.upper()) - ord("A")


def _apply_origin_overrides(rule: ZoneLookupRuleRecord) -> tuple[ZoneLookupRuleRecord, list[str]]:
    risk_tags: list[str] = []
    origin = normalize_origin(rule.origin)
    expected_origin = ORIGIN_BY_PROVINCE.get(normalize_province(rule.province) or "")
    if expected_origin and origin != expected_origin:
        origin = expected_origin
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
        canonical_city=str(row.get("canonical_city") or "") or None,
        priority=int(row.get("priority") or 100),
        active=_parse_bool(row.get("active", True)),
        match_level=str(row.get("match_level") or "") or None,
        note=str(row.get("note") or "") or None,
    )


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off", "inactive"}
