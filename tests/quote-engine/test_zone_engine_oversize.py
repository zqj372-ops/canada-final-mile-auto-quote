from dataclasses import dataclass
from decimal import Decimal

import pytest
from pydantic import ValidationError

from packages.quote_engine.oversize_config import default_oversize_pallet_rule
from packages.quote_engine.oversize_models import HandlingUnitInput
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_engine import ZoneQuoteEngine
from packages.quote_engine.zone_models import (
    AddressType,
    CityAliasRecord,
    PostalCodeCityRecord,
    PostalZoneOverrideRecord,
    ZoneLookupRuleRecord,
    ZonePriceRecord,
    ZoneQuoteRequest,
    ZoneQuoteSourceType,
)


@dataclass
class _Provider:
    def get_preferred_city(self, postal_code: str) -> PostalCodeCityRecord | None:
        return PostalCodeCityRecord(
            postal_code=postal_code,
            preferred_city="Calgary",
            province="AB",
        )

    def get_postal_zone_override(self, postal_code: str) -> PostalZoneOverrideRecord | None:
        return None

    def list_city_aliases(self, province: str | None) -> list[CityAliasRecord]:
        return []

    def list_zone_rules(self, postal_prefix: str) -> list[ZoneLookupRuleRecord]:
        return [
            ZoneLookupRuleRecord(
                postal_prefix="T1X",
                city="CALGARY",
                province="AB",
                origin="calgary",
                zone=1,
                match_level="test",
            )
        ]

    def list_city_zone_rules(
        self, city: str, province: str | None
    ) -> list[ZoneLookupRuleRecord]:
        return []

    def get_zone_price(
        self, origin: str, zone: int, billing_pallets: int
    ) -> ZonePriceRecord | None:
        return ZonePriceRecord(
            origin=origin,
            zone=zone,
            billing_pallets=billing_pallets,
            base_price_usd=Decimal("100.00"),
            source="test",
        )


def _request(**overrides: object) -> ZoneQuoteRequest:
    payload: dict[str, object] = {
        "address_line": "123 Test Street",
        "postal_code": "T1X 0A0",
        "city": "Calgary",
        "province": "AB",
        "cbm": Decimal("2.6"),
        "weight_kg": Decimal("900"),
        "piece_count": 1,
        "packaging_type": "crate",
        "longest_side_cm": Decimal("200"),
        "address_type": AddressType.COMMERCIAL,
        "handling_units": [
            {
                "quantity": 1,
                "packaging_type": "crate",
                "length_cm": Decimal("200"),
                "width_cm": Decimal("130"),
                "height_cm": Decimal("100"),
                "unit_weight_kg": Decimal("900"),
            }
        ],
    }
    payload.update(overrides)
    return ZoneQuoteRequest(**payload)


def test_zone_request_parses_handling_units_and_rejects_unknown_fields() -> None:
    request = _request()

    assert isinstance(request.handling_units[0], HandlingUnitInput)
    assert request.handling_units[0].length_cm == Decimal("200")

    with pytest.raises(ValidationError):
        _request(unexpected_field="must be rejected")


def test_zone_engine_uses_handling_units_and_keeps_oversize_trace_private() -> None:
    result = ZoneQuoteEngine(
        _Provider(),
        pricing_config=ZonePricingConfig(),
        oversize_rule=default_oversize_pallet_rule(),
        oversize_rule_version="7",
    ).quote(_request())

    assert result.source_type is ZoneQuoteSourceType.ZONE_MATRIX
    assert not result.manual_review_required
    assert result.billing_pallets == 3
    assert result.accessorials["oversize_heavy_fee_usd"] == Decimal("75.00")
    assert result.total_price_usd == Decimal("210.00")
    assert result.internal_trace["oversize_rule_version"] == "7"
    assert result.internal_trace["calculator"]["billing_pallets"] == 3
    assert result.internal_trace["vehicle"]["status"] == "FIT"

    public = result.to_public()
    assert public.billing_pallets == 3
    assert public.total_price_usd == Decimal("210.00")
    assert set(public.model_dump()) == {
        "quote_id",
        "billing_pallets",
        "total_price_usd",
        "sales_note",
        "manual_review_required",
        "public_flags",
    }
    assert "pallet_breakdown" not in public.model_dump()
    assert "internal_trace" not in public.model_dump()
    assert "oversize_heavy_fee_usd" not in public.model_dump()


def test_missing_handling_units_is_manual_and_public_hides_candidate_pallets() -> None:
    request = _request(handling_units=[])
    # Keep aggregate values populated to prove the old ceil(CBM / 2) fallback is gone.
    result = ZoneQuoteEngine(_Provider()).quote(request)

    assert result.manual_review_required
    assert result.source_type is ZoneQuoteSourceType.MANUAL_REQUIRED
    assert result.billing_pallets is None
    assert "handling_units_missing" in result.risk_tags
    assert result.internal_trace["calculator"]["billing_pallets"] is None

    public = result.to_public()
    assert public.manual_review_required
    assert public.billing_pallets is None
    assert public.total_price_usd is None
    assert "handling_units_missing" not in public.public_flags


def test_zone_engine_preserves_internal_candidate_when_zone_price_missing() -> None:
    class MissingPriceProvider(_Provider):
        def get_zone_price(
            self, origin: str, zone: int, billing_pallets: int
        ) -> ZonePriceRecord | None:
            return None

    result = ZoneQuoteEngine(MissingPriceProvider()).quote(_request())

    assert result.manual_review_required
    assert result.billing_pallets == 3
    assert result.internal_trace["calculator"]["billing_pallets"] == 3
    public = result.to_public()
    assert public.billing_pallets is None
    assert public.total_price_usd is None


def test_oversize_manual_keeps_internal_candidate_but_public_hides_it() -> None:
    result = ZoneQuoteEngine(_Provider()).quote(
        _request(
            cbm=2.6,
            weight_kg=Decimal("1000.01"),
            handling_units=[
                {
                    "quantity": 1,
                    "packaging_type": "crate",
                    "length_cm": Decimal("200"),
                    "width_cm": Decimal("130"),
                    "height_cm": Decimal("100"),
                    "unit_weight_kg": Decimal("1000.01"),
                }
            ],
        )
    )

    assert result.manual_review_required
    assert result.billing_pallets == 3
    assert "handling_unit_weight_over_auto_limit" in result.risk_tags
    assert result.pallet_breakdown["weight_pallets"] == 3
    assert result.to_public().billing_pallets is None


def test_postal_prefix_manual_keeps_internal_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("packages.quote_engine.zone_engine.extract_fsa", lambda _value: None)

    result = ZoneQuoteEngine(_Provider()).quote(_request())

    assert result.manual_review_required
    assert result.billing_pallets == 3
    assert result.pallet_breakdown["total_size_pallets"] == 3
    assert result.to_public().billing_pallets is None
