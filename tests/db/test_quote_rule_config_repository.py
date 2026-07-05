from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, QuoteRuleConfig
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository


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


def test_quote_rule_config_rows_override_defaults() -> None:
    session = make_session()
    session.add(QuoteRuleConfig(key="fuel_percent", value="12.5", description=None))
    session.add(QuoteRuleConfig(key="detention_free_minutes", value="45", description=None))
    session.commit()

    config = QuoteRuleConfigRepository(session).get_zone_pricing_config()

    assert config.fuel_percent == Decimal("12.5")
    assert config.residential_fee_usd == Decimal("50")
    assert config.detention_free_minutes == 45

