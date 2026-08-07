from collections.abc import Mapping, Sequence
from dataclasses import replace
import re
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

STRICT_FSA_RE = re.compile(r"^[ABCEGHJKLMNPRSTVXY]\d[ABCEGHJKLMNPRSTVWXYZ]$")


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
    return get_province_from_postal_prefix(normalized[:3])


def get_province_from_postal_prefix(postal_prefix: str | None) -> str | None:
    """Return the province implied by a Canadian FSA/postal prefix."""

    prefix = extract_fsa(postal_prefix)
    if not prefix:
        return None
    if prefix[0] == "X":
        if prefix in {"X0A", "X0B", "X0C"}:
            return "NU"
        if prefix in {"X0E", "X0G", "X1A"}:
            return "NT"
        return None
    return PROVINCE_BY_POSTAL_INITIAL.get(prefix[0])


def get_province_from_strict_fsa(postal_prefix: str | None) -> str | None:
    """Return an FSA province only when the value is a canonical three-character FSA."""

    if not postal_prefix:
        return None
    prefix = postal_prefix.upper()
    if postal_prefix != prefix:
        return None
    if not STRICT_FSA_RE.fullmatch(prefix):
        return None
    return get_province_from_postal_prefix(prefix)


def postal_prefix_matches_province(postal_prefix: str | None, province: str | None) -> bool:
    """Check the hard geographic relationship encoded by a Canadian FSA.

    The Zone table contains legacy rows where a city was copied together with
    a prefix from another province. Those rows must never become city-level
    anchors. A prefix that cannot be interpreted is left to the normal lookup
    rules so a future non-standard source is not silently discarded here.
    """

    prefix_province = get_province_from_postal_prefix(postal_prefix)
    normalized_province = normalize_province(province)
    return prefix_province is None or normalized_province is None or prefix_province == normalized_province


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
    invalid_rules = [rule for rule in active_rules if zone_rule_quality_issue(rule)]
    active_rules = [rule for rule in active_rules if is_zone_rule_usable(rule)]
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
    if invalid_rules:
        trace.update(
            {
                "invalid_rule_count": len(invalid_rules),
                "invalid_rule_examples": [_zone_rule_trace(rule) for rule in invalid_rules[:3]],
            }
        )

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
    expected_origin = ORIGIN_BY_PROVINCE.get(normalized_province or "")
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
        match_rules, origin_preference_applied = _prefer_expected_origin_rules(city_filtered, expected_origin)
        groups = _unique_groups(match_rules)
        if len(groups) == 1:
            original = _choose_best_rule(match_rules)
            rule, risk_tags = _apply_origin_overrides(original)
            matched_by = "city_alias" if alias_used else "canonical_city"
            result_risk_tags = list(risk_tags)
            if origin_preference_applied:
                result_risk_tags.append("expected_origin_preferred")
            trace.update(
                {
                    "matched_by": matched_by,
                    "matched_rule_city": rule.canonical_city or rule.city,
                    "candidate_count": len(match_rules),
                    "expected_origin": expected_origin,
                    "origin_preference_applied": origin_preference_applied,
                }
            )
            return ZoneLookupDecision(
                manual_required=False,
                matched_rule=f"{matched_by} + {prefix} + {rule.province} + {rule.city} -> {rule.origin} Zone {rule.zone}",
                rule=rule,
                origin=rule.origin,
                zone=rule.zone,
                confidence=88 if alias_used else 86,
                risk_tags=tuple(result_risk_tags),
                matched_by=matched_by,
                candidate_count=len(match_rules),
                match_trace=trace,
            )
        return ZoneLookupDecision(
            manual_required=True,
            matched_rule=_describe_city_postal_zone_conflict(
                prefix=prefix,
                postal_code=normalized_postal_code,
                input_city=input_city,
                preferred_city=preferred_city,
                rules=match_rules,
                alias_map=alias_map,
            ),
            risk_tags=("split_record_conflict",),
            matched_by="split_record_conflict",
            candidate_count=len(match_rules),
            match_trace={
                **trace,
                "matched_by": "split_record_conflict",
                "unique_group_count": len(groups),
                "expected_origin": expected_origin,
                "origin_preference_applied": origin_preference_applied,
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

    invalid_rules = [rule for rule in rules if rule.active and zone_rule_quality_issue(rule)]
    filtered = _filter_rules(rules, city, province)
    if not filtered:
        if invalid_rules:
            invalid_rule = invalid_rules[0]
            issue = zone_rule_quality_issue(invalid_rule) or "Zone 锚点数据质量异常"
            return ZoneLookupDecision(
                manual_required=True,
                matched_rule=(
                    f"邮编前缀 {prefix or '未知'} 未命中；城市索引中检测到无关的跨省脏记录："
                    f"{issue}。已忽略该记录，请补充 "
                    f"{prefix or '当前邮编前缀'} + {city} + {province} 的可信 Zone 规则。"
                ),
                risk_tags=("zone_not_found", "zone_rule_province_mismatch"),
                matched_by="city_fallback_invalid_anchor",
                candidate_count=len(invalid_rules),
                match_trace={
                    "fsa": prefix,
                    "input_city": city,
                    "province": normalized_province,
                    "candidate_count": len(rules),
                    "invalid_rule_count": len(invalid_rules),
                    "invalid_rule_examples": [_zone_rule_trace(rule) for rule in invalid_rules[:3]],
                    "matched_by": "city_fallback_invalid_anchor",
                },
            )
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

    if prefix:
        exact_prefix_rules = [
            rule for rule in filtered if _normalize_prefix(rule.postal_prefix) == prefix
        ]
        if not exact_prefix_rules:
            prefix_family = f"{prefix[:2]}*" if len(prefix) >= 2 else prefix
            family_rules = [
                rule
                for rule in filtered
                if _normalize_prefix(rule.postal_prefix).startswith(prefix[:2])
            ]
            return ZoneLookupDecision(
                manual_required=True,
                matched_rule=(
                    f"邮编前缀 {prefix} 未在城市 {city} + {province} 的当前有效 FSA 配置中，"
                    f"不能按同邮编族 {prefix_family} 回退匹配 Zone，需要人工确认。"
                ),
                risk_tags=("zone_not_found", "city_zone_prefix_family_low_support"),
                matched_by="city_zone_prefix_not_configured",
                candidate_count=len(family_rules),
                match_trace={
                    "fsa": prefix,
                    "input_city": city,
                    "province": normalized_province,
                    "candidate_count": len(family_rules),
                    "city_filtered_count": len(filtered),
                    "exact_prefix_count": 0,
                    "prefix_family": prefix_family,
                    "prefix_family_count": len(family_rules),
                    "matched_by": "city_zone_prefix_not_configured",
                },
            )
        # A configured city group is authoritative for the supplied FSA. Do
        # not let an origin preference or another city anchor re-expand it.
        filtered = exact_prefix_rules

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
    invalid_origin_candidate_discarded = bool(
        expected_origin
        and any(normalize_origin(rule.origin) != expected_origin for rule in invalid_rules)
    )
    if invalid_origin_candidate_discarded and any(
        normalize_origin(rule.origin) == expected_origin for rule in filtered
    ):
        # Keep the existing diagnostic signal when a stale cross-province
        # candidate was discarded before the expected-origin rule was chosen.
        origin_preference_applied = True
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
                "invalid_rule_count": len(invalid_rules),
                "unique_group_count": len(groups),
                "matched_by": "city_fallback_split_record_conflict",
            },
        )

    original = _choose_best_rule(match_rules)

    rule, risk_tags = _apply_origin_overrides(original)
    fallback_detail = "，使用城市分区"
    result_risk_tags = [*risk_tags, "city_zone_fallback"]
    if origin_preference_applied:
        result_risk_tags.append("expected_origin_preferred")
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
            "invalid_rule_count": len(invalid_rules),
            "matched_by": "city_zone_fallback",
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


def zone_rule_quality_issue(rule: ZoneLookupRuleRecord) -> str | None:
    """Return a deterministic data-quality issue for a Zone rule, if any."""

    prefix_province = get_province_from_postal_prefix(rule.postal_prefix)
    rule_province = normalize_province(rule.province)
    if prefix_province and rule_province and prefix_province != rule_province:
        return (
            f"邮编前缀 {_normalize_prefix(rule.postal_prefix)} 属于 {prefix_province}，"
            f"规则却标为 {rule_province}"
        )
    return None


def is_zone_rule_usable(rule: ZoneLookupRuleRecord) -> bool:
    """Whether a Zone rule is safe to use as pricing evidence."""

    return bool(rule.active and zone_rule_quality_issue(rule) is None)


def _zone_rule_trace(rule: ZoneLookupRuleRecord) -> dict[str, object]:
    return {
        "postal_prefix": _normalize_prefix(rule.postal_prefix),
        "city": rule.canonical_city or rule.city,
        "province": normalize_province(rule.province) or rule.province,
        "inferred_province": get_province_from_postal_prefix(rule.postal_prefix),
        "origin": normalize_origin(rule.origin) or rule.origin,
        "zone": rule.zone,
        "match_level": rule.match_level,
        "note": rule.note,
    }


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
        return [rule for rule in rules if is_zone_rule_usable(rule)]
    return [
        rule
        for rule in rules
        if is_zone_rule_usable(rule) and normalize_province(rule.province) == normalized_province
    ]


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


def _describe_city_postal_zone_conflict(
    *,
    prefix: str,
    postal_code: str | None,
    input_city: str | None,
    preferred_city: str | None,
    rules: Sequence[ZoneLookupRuleRecord],
    alias_map: Mapping[str, str],
) -> str:
    descriptions: list[str] = []
    seen: set[tuple[str, tuple[tuple[str, int], ...]]] = set()

    def append_city(label: str, city: str | None) -> None:
        normalized = _normalize_city_for_lookup(city)
        if not normalized:
            return
        canonical = alias_map.get(normalized, normalized)
        city_rules = _filter_rules_by_canonical_city(rules, [canonical, normalized], alias_map)
        groups = sorted(
            {
                (origin_label(overridden.origin), overridden.zone)
                for rule in city_rules
                for overridden, _ in [_apply_origin_overrides(rule)]
            },
            key=lambda item: (item[0], item[1]),
        )
        if not groups:
            return
        key = (canonical, tuple(groups))
        if key in seen:
            return
        seen.add(key)
        zones = " / ".join(f"{origin} Zone {zone}" for origin, zone in groups)
        descriptions.append(f"{label} → {zones}")

    append_city(f"输入城市 {input_city}", input_city)
    postal_label = postal_code or prefix
    append_city(f"邮编 {postal_label} 对应城市 {preferred_city}", preferred_city)

    if descriptions:
        return f"地址信息对应不同 Zone：{'；'.join(descriptions)}。请核对城市或邮编后再报价。"
    return f"邮编前缀 {prefix} 匹配到多个 Zone 规则，需要人工确认。"


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
            "matched_rule_postal_prefix": _normalize_prefix(rule.postal_prefix),
            "matched_rule_match_level": rule.match_level,
            "matched_rule_note": rule.note,
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
