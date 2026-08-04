from packages.quote_engine.zone_lookup import lookup_zone_by_city_province
from packages.quote_engine.zone_models import ZoneLookupRuleRecord


CALGARY_ACTIVE_FSAS = (
    "T1Y",
    "T2A",
    "T2B",
    "T2C",
    "T2E",
    "T2G",
    "T2H",
    "T2J",
    "T2K",
    "T2L",
    "T2M",
    "T2N",
    "T2P",
    "T2R",
    "T2S",
    "T2T",
    "T2V",
    "T2W",
    "T2X",
    "T2Y",
    "T2Z",
    "T3A",
    "T3B",
    "T3C",
    "T3E",
    "T3G",
    "T3H",
    "T3J",
    "T3K",
    "T3L",
    "T3M",
    "T3N",
    "T3P",
    "T3R",
    "T3S",
)


def _calgary_rules() -> list[ZoneLookupRuleRecord]:
    return [
        ZoneLookupRuleRecord(
            postal_prefix=fsa,
            city="CALGARY",
            canonical_city="CALGARY",
            province="AB",
            origin="calgary",
            zone=1,
            match_level="admin_city_config",
        )
        for fsa in CALGARY_ACTIVE_FSAS
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
    assert decision.match_trace["prefix_family_count"] == 3


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
