from datetime import datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.auth import CurrentActor
from apps.api.db.repositories.fcl_rate_card_repository import FCLQuoteConfigRepository
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.repositories.zone_city_rule_repository import ZoneCityRuleRepository
from apps.api.db.repositories.zone_price_matrix_repository import ZonePriceMatrixRepository
from apps.api.db.session import get_db
from packages.quote_engine.workbench_config import QuoteWorkbenchConfig
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.fcl import FCLFeeLine, FCLQuoteConfig, FCLRateCardPayload


CONFIG_READ_ROLES = ("admin", "operator", "sales", "viewer")

router = APIRouter(prefix="/quote-configs", tags=["quote-configs"])


class ZonePriceMatrixRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    origin: str
    zone: int
    billing_pallets: int
    base_price_usd: Decimal
    source: str | None = None
    last_updated: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ZonePriceMatrixListResponse(BaseModel):
    records: list[ZonePriceMatrixRecord]
    total: int
    origins: list[str]
    zones: list[int]
    billing_pallets: list[int]


class ZonePriceMatrixUpsert(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    origin: str = Field(min_length=1, max_length=32)
    zone: int = Field(ge=1)
    billing_pallets: int = Field(ge=1)
    base_price_usd: Decimal = Field(ge=0)
    source: str | None = None
    last_updated: str | None = None


class ZonePriceMatrixUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    base_price_usd: Decimal | None = Field(default=None, ge=0)
    source: str | None = None
    last_updated: str | None = None


class ZoneCityRuleRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    postal_prefix: str
    city: str
    province: str
    origin: str
    zone: int
    canonical_city: str | None = None
    priority: int
    active: bool
    match_level: str | None = None
    note: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class ZoneCityRuleListResponse(BaseModel):
    records: list[ZoneCityRuleRecord]
    total: int
    city_count: int
    postal_prefix_count: int


class ZoneCityRuleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    postal_prefix: str = Field(min_length=3, max_length=16)
    city: str = Field(min_length=1, max_length=100)
    province: str = Field(min_length=2, max_length=32)
    origin: str = Field(min_length=1, max_length=32)
    zone: int = Field(ge=1)
    canonical_city: str | None = Field(default=None, max_length=100)
    priority: int = Field(default=100, ge=1, le=1000)
    note: str | None = Field(default=None, max_length=1000)


class ZoneCityRuleUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    postal_prefix: str | None = Field(default=None, min_length=3, max_length=16)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    province: str | None = Field(default=None, min_length=2, max_length=32)
    origin: str | None = Field(default=None, min_length=1, max_length=32)
    zone: int | None = Field(default=None, ge=1)
    canonical_city: str | None = Field(default=None, max_length=100)
    priority: int | None = Field(default=None, ge=1, le=1000)
    note: str | None = Field(default=None, max_length=1000)


class ZoneCityRuleGroupItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    id: int | None = Field(default=None, ge=1)
    postal_prefix: str = Field(min_length=3, max_length=16)
    origin: str = Field(min_length=1, max_length=32)
    zone: int = Field(ge=1)
    priority: int = Field(default=100, ge=1, le=1000)
    note: str | None = Field(default=None, max_length=1000)


class ZoneCityRuleGroupSave(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    city: str = Field(min_length=1, max_length=100)
    province: str = Field(min_length=2, max_length=32)
    canonical_city: str | None = Field(default=None, max_length=100)
    rules: list[ZoneCityRuleGroupItem] = Field(default_factory=list, max_length=200)
    deactivate_ids: list[int] = Field(default_factory=list, max_length=200)


class ZoneCityRuleGroupSaveResponse(BaseModel):
    records: list[ZoneCityRuleRecord]
    created_count: int
    updated_count: int
    deactivated_count: int


class FCLConfigAdminResponse(BaseModel):
    draft: FCLQuoteConfig
    published: FCLQuoteConfig | None
    published_version: int


class FCLRateCardRecord(FCLRateCardPayload):
    id: int
    status: str
    created_at: datetime | None = None
    updated_at: datetime | None = None


class FCLPublishResponse(BaseModel):
    config: FCLQuoteConfig
    published_version: int


@router.get(
    "/workbench",
    response_model=QuoteWorkbenchConfig,
    dependencies=[Depends(require_roles(*CONFIG_READ_ROLES))],
)
def get_workbench_config(db: Session = Depends(get_db)) -> QuoteWorkbenchConfig:
    return QuoteRuleConfigRepository(db).get_workbench_config()


@router.put(
    "/workbench",
    response_model=QuoteWorkbenchConfig,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def update_workbench_config(
    payload: QuoteWorkbenchConfig,
    db: Session = Depends(get_db),
) -> QuoteWorkbenchConfig:
    return QuoteRuleConfigRepository(db).save_workbench_config(payload)


@router.get(
    "/zone-pricing",
    response_model=ZonePricingConfig,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def get_zone_pricing_config(db: Session = Depends(get_db)) -> ZonePricingConfig:
    return QuoteRuleConfigRepository(db).get_zone_pricing_config()


@router.put(
    "/zone-pricing",
    response_model=ZonePricingConfig,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def update_zone_pricing_config(
    payload: ZonePricingConfig,
    db: Session = Depends(get_db),
) -> ZonePricingConfig:
    return QuoteRuleConfigRepository(db).save_zone_pricing_config(payload)


@router.get(
    "/zone-price-matrix",
    response_model=ZonePriceMatrixListResponse,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def list_zone_price_matrix(
    origin: str | None = None,
    zone: int | None = Query(default=None, ge=1),
    billing_pallets: int | None = Query(default=None, ge=1),
    limit: int = Query(default=2000, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return ZonePriceMatrixRepository(db).list_prices(
        origin=origin,
        zone=zone,
        billing_pallets=billing_pallets,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/zone-price-matrix",
    response_model=ZonePriceMatrixRecord,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def upsert_zone_price_matrix(
    payload: ZonePriceMatrixUpsert,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    try:
        record = ZonePriceMatrixRepository(db).upsert_price(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ZonePriceMatrixRepository(db).to_dict(record)


@router.patch(
    "/zone-price-matrix/{record_id}",
    response_model=ZonePriceMatrixRecord,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def update_zone_price_matrix(
    record_id: int,
    payload: ZonePriceMatrixUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    record = ZonePriceMatrixRepository(db).update_price(
        record_id,
        **payload.model_dump(exclude_unset=True),
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Zone price matrix record not found.")
    return ZonePriceMatrixRepository(db).to_dict(record)


@router.get(
    "/zone-city-rules",
    response_model=ZoneCityRuleListResponse,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def list_zone_city_rules(
    origin: str | None = None,
    zone: int | None = Query(default=None, ge=1),
    search: str | None = Query(default=None, max_length=100),
    include_inactive: bool = False,
    limit: int = Query(default=500, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    return ZoneCityRuleRepository(db).list_rules(
        origin=origin,
        zone=zone,
        search=search,
        include_inactive=include_inactive,
        limit=limit,
        offset=offset,
    )


@router.post(
    "/zone-city-rules",
    response_model=ZoneCityRuleRecord,
    status_code=201,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def create_zone_city_rule(
    payload: ZoneCityRuleCreate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = ZoneCityRuleRepository(db)
    try:
        record = repository.create_rule(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.to_dict(record)


@router.patch(
    "/zone-city-rules/{record_id}",
    response_model=ZoneCityRuleRecord,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def update_zone_city_rule(
    record_id: int,
    payload: ZoneCityRuleUpdate,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = ZoneCityRuleRepository(db)
    try:
        record = repository.update_rule(record_id, payload.model_dump(exclude_unset=True))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail="Zone city rule not found.")
    return repository.to_dict(record)


@router.delete(
    "/zone-city-rules/{record_id}",
    response_model=ZoneCityRuleRecord,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def deactivate_zone_city_rule(
    record_id: int,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = ZoneCityRuleRepository(db)
    record = repository.deactivate_rule(record_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Zone city rule not found.")
    return repository.to_dict(record)


@router.put(
    "/zone-city-rule-groups",
    response_model=ZoneCityRuleGroupSaveResponse,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def save_zone_city_rule_group(
    payload: ZoneCityRuleGroupSave,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = ZoneCityRuleRepository(db)
    try:
        return repository.save_city_group(
            city=payload.city,
            province=payload.province,
            canonical_city=payload.canonical_city,
            rules=[rule.model_dump() for rule in payload.rules],
            deactivate_ids=payload.deactivate_ids,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get(
    "/fcl",
    response_model=FCLConfigAdminResponse,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def get_fcl_config(db: Session = Depends(get_db)) -> dict[str, object]:
    return FCLQuoteConfigRepository(db).admin_snapshot()


@router.put(
    "/fcl/draft",
    response_model=FCLConfigAdminResponse,
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def save_fcl_config_draft(
    payload: FCLQuoteConfig,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    repository = FCLQuoteConfigRepository(db)
    try:
        repository.save_draft(payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return repository.admin_snapshot()


@router.post(
    "/fcl/validate",
    response_model=dict[str, object],
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def validate_fcl_config(db: Session = Depends(get_db)) -> dict[str, object]:
    errors = FCLQuoteConfigRepository(db).validate_draft()
    return {"valid": not errors, "errors": errors}


@router.post(
    "/fcl/publish",
    response_model=FCLPublishResponse,
)
def publish_fcl_config(
    db: Session = Depends(get_db),
    actor: CurrentActor = Depends(require_roles(*ADMIN_ROLES)),
) -> dict[str, object]:
    try:
        config, version = FCLQuoteConfigRepository(db).publish_draft(actor)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"config": config, "published_version": version}


@router.get(
    "/fcl-rate-cards",
    response_model=list[FCLRateCardRecord],
    dependencies=[Depends(require_roles(*ADMIN_ROLES))],
)
def list_fcl_rate_cards(
    status: str | None = Query(default=None, pattern="^(draft|published)$"),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    repository = FCLQuoteConfigRepository(db)
    return [repository.to_dict(record) for record in repository.list_rate_cards(status=status)]


@router.post(
    "/fcl-rate-cards",
    response_model=FCLRateCardRecord,
    status_code=201,
)
def create_fcl_rate_card(
    payload: FCLRateCardPayload,
    db: Session = Depends(get_db),
    _actor: CurrentActor = Depends(require_roles(*ADMIN_ROLES)),
) -> dict[str, object]:
    repository = FCLQuoteConfigRepository(db)
    try:
        return repository.to_dict(repository.create_rate_card(payload))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.put(
    "/fcl-rate-cards/{record_id}",
    response_model=FCLRateCardRecord,
)
def update_fcl_rate_card(
    record_id: int,
    payload: FCLRateCardPayload,
    db: Session = Depends(get_db),
    _actor: CurrentActor = Depends(require_roles(*ADMIN_ROLES)),
) -> dict[str, object]:
    repository = FCLQuoteConfigRepository(db)
    try:
        return repository.to_dict(repository.update_rate_card(record_id, payload))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post(
    "/fcl-rate-cards/{record_id}/publish",
    response_model=FCLRateCardRecord,
)
def publish_fcl_rate_card(
    record_id: int,
    db: Session = Depends(get_db),
    _actor: CurrentActor = Depends(require_roles(*ADMIN_ROLES)),
) -> dict[str, object]:
    repository = FCLQuoteConfigRepository(db)
    try:
        return repository.to_dict(repository.publish_rate_card(record_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
