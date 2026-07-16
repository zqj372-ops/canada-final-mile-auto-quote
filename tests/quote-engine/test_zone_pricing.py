from decimal import Decimal

from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_models import AddressType
from packages.quote_engine.zone_pricing import calculate_zone_price


def test_calculate_zone_price_default_config_keeps_existing_result() -> None:
    result = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.COMMERCIAL,
        requires_appointment=True,
    )

    assert result.fuel_usd == Decimal("42.00")
    assert result.accessorials["appointment_fee_usd"] == Decimal("50.00")
    assert result.total_price_usd == Decimal("212.00")


def test_custom_fuel_percent_is_applied() -> None:
    result = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.COMMERCIAL,
        config=ZonePricingConfig(fuel_percent=Decimal("10")),
    )

    assert result.fuel_usd == Decimal("12.00")
    assert result.total_price_usd == Decimal("132.00")


def test_zone_fuel_percent_override_and_default() -> None:
    config = ZonePricingConfig(
        fuel_percent=Decimal("35"),
        fuel_percent_by_zone={"calgary|1": Decimal("10")},
    )

    overridden = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.COMMERCIAL,
        origin="Calgary",
        zone=1,
        config=config,
    )
    fallback = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.COMMERCIAL,
        origin="calgary",
        zone=2,
        config=config,
    )

    assert overridden.fuel_usd == Decimal("12.00")
    assert overridden.total_price_usd == Decimal("132.00")
    assert fallback.fuel_usd == Decimal("42.00")


def test_custom_residential_fee_is_applied() -> None:
    result = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.RESIDENTIAL,
        config=ZonePricingConfig(residential_fee_usd=Decimal("75")),
    )

    assert result.accessorials["residential_fee_usd"] == Decimal("75.00")
    assert result.total_price_usd == Decimal("237.00")
