from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.db.models import Base, VendorRateRule
from apps.api.db.repositories.rate_rule_repository import RateRuleRepository
from packages.quote_engine.models import ShipmentInput, SourceType


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def add_rule(session: Session, **overrides: object) -> VendorRateRule:
    values = {
        "rule_id": "rule-1",
        "source_type": SourceType.FSA.value,
        "origin_warehouse": "Toronto",
        "vendor_name": "Demo Carrier",
        "province": "ON",
        "city": "Mississauga",
        "fsa": "L5T",
        "postal_code": None,
        "pallet_min": 1,
        "pallet_max": 3,
        "weight_min_kg": None,
        "weight_max_kg": Decimal("1000.00"),
        "base_cost_cad": Decimal("100.00"),
        "fuel_percent": Decimal("10.00"),
        "appointment_fee_cad": Decimal("15.00"),
        "liftgate_fee_cad": Decimal("0.00"),
        "residential_fee_cad": Decimal("0.00"),
        "limited_access_fee_cad": Decimal("0.00"),
        "remote_fee_cad": Decimal("0.00"),
        "status": "active",
    }
    values.update(overrides)
    record = VendorRateRule(**values)
    session.add(record)
    session.commit()
    return record


def test_database_candidate_rule_converts_to_rate_rule() -> None:
    session = make_session()
    add_rule(session)

    shipment = ShipmentInput(
        postal_code="L5T 2X3",
        city="Mississauga",
        province="ON",
        origin_warehouse="Toronto",
        pallet_count=2,
        weight_kg=Decimal("850"),
    )

    rules = RateRuleRepository(session).list_candidate_rules(shipment)

    assert len(rules) == 1
    assert rules[0].source_type == SourceType.FSA
    assert rules[0].base_cost_cad == Decimal("100.00")


def test_weight_interval_mismatch_is_not_candidate() -> None:
    session = make_session()
    add_rule(session, weight_max_kg=Decimal("100.00"))

    shipment = ShipmentInput(
        postal_code="L5T 2X3",
        city="Mississauga",
        province="ON",
        origin_warehouse="Toronto",
        pallet_count=2,
        weight_kg=Decimal("850"),
    )

    rules = RateRuleRepository(session).list_candidate_rules(shipment)

    assert rules == []


def test_inactive_rule_is_not_candidate() -> None:
    session = make_session()
    add_rule(session, status="inactive")

    shipment = ShipmentInput(
        postal_code="L5T 2X3",
        city="Mississauga",
        province="ON",
        origin_warehouse="Toronto",
        pallet_count=2,
        weight_kg=Decimal("850"),
    )

    rules = RateRuleRepository(session).list_candidate_rules(shipment)

    assert rules == []

