from apps.api.services.llm_auxiliary_advice_service import (
    _curated_safe_zone_options,
    _zone_option_supported,
)


def _zone_option(*, postal_prefix: str, city: str, zone: int) -> dict[str, object]:
    return {
        "postal_prefix": postal_prefix,
        "city": city,
        "province": "ON",
        "origin": "toronto",
        "zone": zone,
        "expected_origin_match": True,
        "has_price_for_billing_pallets": True,
        "base_price_usd": "90.00",
    }


def test_other_city_fsa_options_cannot_be_promoted_to_safe_zone_evidence() -> None:
    zone_options = [
        _zone_option(postal_prefix="L3L", city="WOODBRIDGE", zone=2),
        _zone_option(postal_prefix="L3B", city="WELLAND", zone=5),
    ]

    curated = _curated_safe_zone_options(
        zone_options,
        postal_prefix="L3K",
        city="Port Colborne",
        expected_origin="toronto",
    )
    evidence = {"zone_options": zone_options, "curated_safe_options": curated}

    assert curated == []
    assert _zone_option_supported(evidence, "toronto", 2) is False
    assert _zone_option_supported(evidence, "toronto", 5) is False


def test_same_city_expected_origin_option_remains_safe_evidence() -> None:
    zone_options = [
        _zone_option(postal_prefix="L3L", city="WOODBRIDGE", zone=2),
        _zone_option(postal_prefix="L3J", city="PORT COLBORNE", zone=5),
    ]

    curated = _curated_safe_zone_options(
        zone_options,
        postal_prefix="L3K",
        city="Port Colborne",
        expected_origin="toronto",
    )
    evidence = {"zone_options": zone_options, "curated_safe_options": curated}

    assert len(curated) == 1
    assert curated[0]["basis"] == "same_city_expected_origin"
    assert curated[0]["zone"] == 5
    assert _zone_option_supported(evidence, "toronto", 5) is True
    assert _zone_option_supported(evidence, "toronto", 2) is False
