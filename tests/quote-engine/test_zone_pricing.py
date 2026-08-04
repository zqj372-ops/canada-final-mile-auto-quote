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


def test_zone_price_switch_defaults_and_explicit_overrides() -> None:
    config = ZonePricingConfig(
        zone_price_enabled_by_zone={
            "calgary|1": False,
            "calgary|8": True,
        }
    )

    assert config.zone_price_enabled_for("calgary", 1) is False
    assert config.zone_price_enabled_for("calgary", 7) is True
    assert config.zone_price_enabled_for("calgary", 8) is True
    assert config.zone_price_enabled_for("calgary", 9) is False
    assert config.zone_price_enabled_for(None, 1) is False


def test_zone_price_global_switch_and_default_cutoff_precedence() -> None:
    globally_disabled = ZonePricingConfig(
        zone_price_enabled=False,
        zone_price_enabled_by_zone={"calgary|8": True},
    )
    custom_cutoff = ZonePricingConfig(
        max_auto_quote_zone=5,
        zone_price_enabled_by_zone={"calgary|8": True},
    )
    unlimited = ZonePricingConfig(max_auto_quote_zone=None)

    assert globally_disabled.zone_price_enabled_for("calgary", 1) is False
    assert globally_disabled.zone_price_enabled_for("calgary", 8) is False
    assert custom_cutoff.zone_price_enabled_for("calgary", 5) is True
    assert custom_cutoff.zone_price_enabled_for("calgary", 6) is False
    assert custom_cutoff.zone_price_enabled_for("calgary", 8) is True
    assert unlimited.zone_price_enabled_for("calgary", 99) is True


def test_custom_residential_fee_is_applied() -> None:
    result = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.RESIDENTIAL,
        config=ZonePricingConfig(residential_fee_usd=Decimal("75")),
    )

    assert result.accessorials["residential_fee_usd"] == Decimal("75.00")
    assert result.total_price_usd == Decimal("237.00")


def test_additional_accessorials_are_added_without_recomputing_pallets() -> None:
    result = calculate_zone_price(
        base_price_usd=Decimal("120.00"),
        address_type=AddressType.COMMERCIAL,
        additional_accessorials={
            "oversize_footprint_fee_usd": Decimal("25"),
            "oversize_heavy_fee_usd": Decimal("75"),
        },
    )

    assert result.accessorials["oversize_footprint_fee_usd"] == Decimal("25.00")
    assert result.accessorials["oversize_heavy_fee_usd"] == Decimal("75.00")
    assert result.total_price_usd == Decimal("262.00")
