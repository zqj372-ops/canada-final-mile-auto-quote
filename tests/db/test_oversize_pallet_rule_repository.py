from decimal import Decimal

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from apps.api.auth import CurrentActor
from apps.api.db.models import Base, OversizePalletRuleVersion, QuoteRuleConfig
from apps.api.db.repositories.oversize_pallet_rule_repository import (
    OVERSIZE_PALLET_RULE_DRAFT_KEY,
    OversizePalletRuleRepository,
)
from packages.quote_engine.oversize_config import default_oversize_pallet_rule


def make_session() -> Session:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)()


def test_missing_records_use_default_rule_and_zero_published_version() -> None:
    session = make_session()

    repository = OversizePalletRuleRepository(session)
    draft = repository.get_draft()
    published, version = repository.get_published()

    assert draft.model_dump(mode="json") == default_oversize_pallet_rule().model_dump(mode="json")
    assert draft.rule_id == "NA_OVERSIZE_RULE_V2"
    assert published is not None
    assert published.rule_id == "NA_OVERSIZE_RULE_V2"
    assert version == 0


def test_draft_validation_publish_and_immutable_snapshot_readback() -> None:
    session = make_session()
    repository = OversizePalletRuleRepository(session)
    draft = default_oversize_pallet_rule().model_copy(update={"medium_oversize_surcharge": Decimal("77")})

    repository.save_draft(draft)
    assert repository.validate_draft() == []
    first, first_version = repository.publish_draft(
        CurrentActor(user_id=None, api_key_id=None, name="Admin", role="admin")
    )
    row = session.scalar(
        select(OversizePalletRuleVersion).where(OversizePalletRuleVersion.version == first_version)
    )
    assert first_version == 1
    assert first.medium_oversize_surcharge == Decimal("77")
    assert row is not None
    first_snapshot = row.config_json

    next_draft = default_oversize_pallet_rule().model_copy(update={"medium_oversize_surcharge": Decimal("88")})
    repository.save_draft(next_draft)
    second, second_version = repository.publish_draft(
        CurrentActor(user_id=None, api_key_id=None, name="Admin", role="admin")
    )

    assert second_version == 2
    assert second.medium_oversize_surcharge == Decimal("88")
    session.expire_all()
    first_row = session.scalar(
        select(OversizePalletRuleVersion).where(OversizePalletRuleVersion.version == first_version)
    )
    assert first_row is not None
    assert first_row.config_json == first_snapshot
    assert first_row.config_json["medium_oversize_surcharge"] == "77"
    published, published_version = repository.get_published()
    assert published is not None
    assert published_version == 2
    assert published.model_dump(mode="json")["medium_oversize_surcharge"] == "88"


def test_publish_retries_when_concurrent_publish_races_same_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = make_session()
    repository = OversizePalletRuleRepository(session)
    draft = default_oversize_pallet_rule()
    repository.save_draft(draft)

    # A concurrent publisher has already committed version 1.
    session.add(
        OversizePalletRuleVersion(
            rule_id=draft.rule_id,
            version=1,
            config_json=draft.model_dump(mode="json"),
            published_by="concurrent-admin",
            status="published",
        )
    )
    session.commit()

    real_scalar = session.scalar
    stale_read = {"active": True}

    def stale_max_once(*args: object, **kwargs: object) -> object:
        # First attempt reads a stale max (0), as if another publisher
        # committed version 1 between our max query and our insert.  The
        # unique constraint then fires IntegrityError; the retry must
        # recompute max(version)+1 instead of surfacing a 500.
        if stale_read["active"]:
            stale_read["active"] = False
            return 0
        return real_scalar(*args, **kwargs)

    monkeypatch.setattr(session, "scalar", stale_max_once)

    _config, version = repository.publish_draft(
        CurrentActor(user_id=None, api_key_id=None, name="Admin", role="admin")
    )

    assert version == 2
    assert set(session.scalars(select(OversizePalletRuleVersion.version)).all()) == {1, 2}


def test_draft_is_stored_as_quote_rule_config_json() -> None:
    session = make_session()
    repository = OversizePalletRuleRepository(session)

    repository.save_draft(default_oversize_pallet_rule())

    record = session.get(QuoteRuleConfig, OVERSIZE_PALLET_RULE_DRAFT_KEY)
    assert record is not None
    assert record.value
    assert repository.get_draft().rule_id == "NA_OVERSIZE_RULE_V2"


def test_validate_draft_reports_invalid_pallet_rule_data() -> None:
    session = make_session()
    session.add(
        QuoteRuleConfig(
            key=OVERSIZE_PALLET_RULE_DRAFT_KEY,
            value='{"rule_id":"NA_OVERSIZE_RULE_V2","max_auto_vehicles":4}',
            description="Oversize pallet draft configuration",
        )
    )
    session.commit()

    errors = OversizePalletRuleRepository(session).validate_draft()

    assert errors
    assert any("max_auto_vehicles" in error for error in errors)


@pytest.mark.parametrize(
    "update",
    [
        {"mild_oversize_length_cm": Decimal("160")},
        {"vehicle_profiles": []},
        {
            "vehicle_profiles": [
                default_oversize_pallet_rule().vehicle_profiles[0].model_copy(
                    update={"payload_kg": Decimal("0")}
                ),
                *default_oversize_pallet_rule().vehicle_profiles[1:],
            ]
        },
        {
            "vehicle_profiles": [
                default_oversize_pallet_rule().vehicle_profiles[0].model_copy(
                    update={"volume_cbm": Decimal("0")}
                ),
                *default_oversize_pallet_rule().vehicle_profiles[1:],
            ]
        },
        {"max_auto_vehicles": 4},
    ],
    ids=["trigger-line-order", "missing-vehicle", "non-positive-payload", "non-positive-volume", "too-many-vehicles"],
)
def test_save_draft_rejects_invalid_rule_constraints(update: dict[str, object]) -> None:
    session = make_session()
    invalid = default_oversize_pallet_rule().model_copy(update=update)

    with pytest.raises(ValueError):
        OversizePalletRuleRepository(session).save_draft(invalid)


@pytest.mark.parametrize("config_json", [None, {}], ids=["json-null", "empty-object"])
def test_published_snapshot_rejects_empty_config_json(config_json: object) -> None:
    session = make_session()
    session.add(
        OversizePalletRuleVersion(
            rule_id="NA_OVERSIZE_RULE_V2",
            version=1,
            config_json=config_json,
            status="published",
        )
    )

    with pytest.raises(IntegrityError):
        session.commit()


def test_invalid_published_snapshot_is_not_replaced_by_default_rule() -> None:
    session = make_session()
    session.add(
        OversizePalletRuleVersion(
            rule_id="BROKEN_PUBLISHED_RULE",
            version=7,
            config_json={"rule_id": "BROKEN_PUBLISHED_RULE", "vehicle_profiles": []},
            status="published",
        )
    )
    session.commit()

    published, version = OversizePalletRuleRepository(session).get_published()

    assert version == 7
    assert published == {
        "rule_id": "BROKEN_PUBLISHED_RULE",
        "invalid_reason": "published_snapshot_invalid",
    }
    assert published != default_oversize_pallet_rule().model_dump(mode="json")
    assert OversizePalletRuleRepository(session).admin_snapshot()["published"] is None
