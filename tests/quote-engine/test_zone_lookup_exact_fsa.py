from packages.quote_engine.zone_lookup import lookup_zone_by_city_province
from packages.quote_engine.zone_models import ZoneLookupRuleRecord


def _calgary_rules() -> list[ZoneLookupRuleRecord]:
    return [
        ZoneLookupRuleRecord(
            postal_prefix="T3S",
            city="CALGARY",
            canonical_city="CALGARY",
            province="AB",
            origin="calgary",
            zone=1,
            match_level="admin_city_config",
        ),
        ZoneLookupRuleRecord(
            postal_prefix="T2A",
            city="CALGARY",
            canonical_city="CALGARY",
            province="AB",
            origin="calgary",
            zone=1,
            match_level="admin_city_config",
        ),
    ]


def test_unconfigured_fsa_cannot_borrow_same_postal_family_zone() -> None:
    decision = lookup_zone_by_city_province(
        city="Calgary",
        province="AB",
        rules=_calgary_rules(),
        requested_postal_prefix="T3Z",
    )

    assert decision.manual_required is True
    assert decision.origin is None
    assert decision.zone is None
    assert decision.matched_by == "city_zone_prefix_not_configured"
    assert "T3Z" in decision.matched_rule
    assert decision.match_trace["prefix_family"] == "T3*"
    assert decision.match_trace["prefix_family_count"] == 1


def test_configured_fsa_can_still_match_exact_rule() -> None:
    decision = lookup_zone_by_city_province(
        city="Calgary",
        province="AB",
        rules=_calgary_rules(),
        requested_postal_prefix="T3S",
    )

    assert decision.manual_required is False
    assert decision.origin == "calgary"
    assert decision.zone == 1
    assert decision.matched_by == "city_zone_fallback"
    assert decision.match_trace["fsa"] == "T3S"
