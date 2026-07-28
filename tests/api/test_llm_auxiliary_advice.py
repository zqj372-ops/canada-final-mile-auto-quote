from apps.api.services.llm_auxiliary_advice_service import (
    LLMAuxiliaryAdviceService,
    apply_llm_auxiliary_advice_if_available,
    _curated_safe_zone_options,
    _zone_option_supported,
)
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_models import (
    AddressType,
    ZoneQuoteRequest,
    ZoneQuoteResult,
    ZoneQuoteSourceType,
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


def test_llm_auxiliary_entry_points_never_change_a_quote() -> None:
    request = ZoneQuoteRequest(
        postal_code="L4K 2N2",
        city="Concord",
        province="ON",
        cbm=1,
        weight_kg=100,
        piece_count=1,
        packaging_type="carton",
        address_type=AddressType.COMMERCIAL,
    )
    result = ZoneQuoteResult(
        source_type=ZoneQuoteSourceType.MANUAL_REQUIRED,
        confidence=0,
        manual_review_required=True,
        matched_rule="No verified zone.",
    )

    assert (
        apply_llm_auxiliary_advice_if_available(
            None,  # type: ignore[arg-type]
            request,
            result,
            pricing_config=ZonePricingConfig(),
        )
        is result
    )

    service = object.__new__(LLMAuxiliaryAdviceService)
    assert service.correct(request, result) is result
