from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, QuoteRuleConfig
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from packages.quote_engine.workbench_config import QuoteWorkbenchConfig
from packages.quote_engine.zone_config import ZonePricingConfig


def make_session():
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_quote_rule_config_missing_rows_uses_defaults() -> None:
    session = make_session()

    config = QuoteRuleConfigRepository(session).get_zone_pricing_config()

    assert config.fuel_percent == Decimal("35")
    assert config.residential_fee_usd == Decimal("50")
    assert config.detention_free_minutes == 30
    assert config.zone_price_enabled is True
    assert config.max_auto_quote_zone == 7
    assert config.zone_price_enabled_for("toronto", 7) is True
    assert config.zone_price_enabled_for("toronto", 8) is False


def test_quote_rule_config_rows_override_defaults() -> None:
    session = make_session()
    session.add(QuoteRuleConfig(key="fuel_percent", value="12.5", description=None))
    session.add(QuoteRuleConfig(key="detention_free_minutes", value="45", description=None))
    session.commit()

    config = QuoteRuleConfigRepository(session).get_zone_pricing_config()

    assert config.fuel_percent == Decimal("12.5")
    assert config.residential_fee_usd == Decimal("50")
    assert config.detention_free_minutes == 45


def test_zone_fuel_percent_overrides_round_trip() -> None:
    session = make_session()
    repository = QuoteRuleConfigRepository(session)

    repository.save_zone_pricing_config(
        ZonePricingConfig(fuel_percent_by_zone={"calgary|1": Decimal("18.5")})
    )

    config = repository.get_zone_pricing_config()
    assert config.fuel_percent_by_zone == {"calgary|1": Decimal("18.5")}


def test_zone_price_switch_overrides_round_trip() -> None:
    session = make_session()
    repository = QuoteRuleConfigRepository(session)

    repository.save_zone_pricing_config(
        ZonePricingConfig(
            zone_price_enabled_by_zone={
                "calgary|1": False,
                "calgary|8": True,
            }
        )
    )

    config = repository.get_zone_pricing_config()
    assert config.zone_price_enabled_by_zone == {
        "calgary|1": False,
        "calgary|8": True,
    }
    assert config.zone_price_enabled_for("calgary", 1) is False
    assert config.zone_price_enabled_for("calgary", 8) is True


def test_workbench_and_standalone_zone_pricing_writes_stay_in_sync() -> None:
    session = make_session()
    repository = QuoteRuleConfigRepository(session)

    repository.save_workbench_config(
        QuoteWorkbenchConfig(
            zone_pricing=ZonePricingConfig(
                max_auto_quote_zone=5,
                zone_price_enabled_by_zone={"toronto|8": True},
            )
        )
    )

    pricing = repository.get_zone_pricing_config()
    assert pricing.max_auto_quote_zone == 5
    assert pricing.zone_price_enabled_for("toronto", 6) is False
    assert pricing.zone_price_enabled_for("toronto", 8) is True

    repository.save_zone_pricing_config(
        pricing.model_copy(
            update={
                "zone_price_enabled": False,
                "max_auto_quote_zone": None,
            }
        )
    )

    workbench = repository.get_workbench_config()
    assert workbench.zone_pricing.zone_price_enabled is False
    assert workbench.zone_pricing.max_auto_quote_zone is None
    assert workbench.zone_pricing.zone_price_enabled_by_zone == {"toronto|8": True}
