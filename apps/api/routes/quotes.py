import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.orm import Session

from apps.api.auth import CurrentActor, QUOTE_WRITE_ROLES, require_roles
from apps.api.db.session import get_db
from apps.api.services.quote_service import (
    calculate_vendor_quote,
    calculate_zone_quote as calculate_zone_quote_service,
    calculate_zone_quote_preview as calculate_zone_quote_preview_service,
    validate_zone_quote_request,
)
from apps.api.services.source_status_service import PREVIEW_CONTRACT_VERSION, SourceStatus, quote_version
from packages.quote_engine.models import QuoteResult, ShipmentInput
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])
SourceRefId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")]


class ZoneQuoteWithNotifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote: ZoneQuoteRequest
    notify_email: bool = False
    email_config_id: int | None = None
    notify_wecom: bool = False
    wecom_bot_id: int | None = None

    @model_validator(mode="before")
    @classmethod
    def wrap_flat_quote(cls, value: object) -> object:
        if isinstance(value, dict) and "quote" not in value:
            return {"quote": value}
        return value


class ZoneQuotePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    origin: str = Field(min_length=1, max_length=32)
    effective_date: date
    quote: ZoneQuoteRequest

    @model_validator(mode="before")
    @classmethod
    def wrap_flat_quote(cls, value: object) -> object:
        if isinstance(value, dict) and "quote" not in value:
            return {"quote": value}
        return value

    @model_validator(mode="before")
    @classmethod
    def require_explicit_pricing_fields(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        quote = value.get("quote", value)
        if not isinstance(quote, dict):
            return value
        required_fields = (
            "cbm",
            "weight_kg",
            "piece_count",
            "packaging_type",
            "longest_side_cm",
            "address_type",
            "requires_liftgate",
            "requires_pallet_jack",
            "requires_appointment",
            "explicit_pallet_count",
            "is_stackable",
            "detention_minutes",
        )
        missing = [field for field in required_fields if field not in quote]
        if missing:
            raise ValueError(f"preview quote fields are required: {', '.join(missing)}")
        for field in ("cbm", "weight_kg", "longest_side_cm"):
            try:
                value_as_decimal = Decimal(str(quote[field]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be greater than zero for preview") from exc
            if value_as_decimal <= 0:
                raise ValueError(f"{field} must be greater than zero for preview")
        explicit_pallet_count = quote["explicit_pallet_count"]
        if explicit_pallet_count is not None:
            try:
                value_as_decimal = Decimal(str(explicit_pallet_count))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError("explicit_pallet_count must be null or at least one for preview") from exc
            if value_as_decimal < 1:
                raise ValueError("explicit_pallet_count must be null or at least one for preview")
        return value


class ZoneQuotePreviewFee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(pattern=r"^\d+\.\d{2}$")
    currency: Literal["USD"] = "USD"


class ZoneQuotePreviewLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    label: str = Field(min_length=1, max_length=200)
    amount: ZoneQuotePreviewFee
    pricing_basis: str = Field(min_length=1, max_length=500)
    source_ref_ids: list[SourceRefId] = Field(min_length=1)


class ZoneQuotePreviewResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_id: str | None
    quote_version: str | None
    status: Literal["quoted", "manual_required", "unavailable"]
    source_type: str
    origin: str | None
    zone: int | None
    billing_pallets: int | None
    fees: dict[str, ZoneQuotePreviewFee]
    test_data: bool
    manual_review_required: bool
    matched_by: str | None
    rule_version: str | None
    data_version: str | None
    valid_from: str | None
    valid_to: str | None
    source_ref: str | None
    service_version: str | None
    contract_version: str
    release_id: str | None
    release_hash: str | None
    snapshot_hash: str | None
    published_at: str | None
    reasons: list[str]
    quote_status: Literal["calculated", "manual_review", "not_calculable"]
    currency: Literal["USD"]
    total: ZoneQuotePreviewFee | None
    line_items: list[ZoneQuotePreviewLineItem]
    source_ref_ids: list[SourceRefId]
    sendable: Literal[False]
    tenant: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    effective_date: str
    ready: bool


@router.post("/calculate", response_model=QuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_quote(shipment: ShipmentInput, db: Session = Depends(get_db)) -> QuoteResult:
    return calculate_vendor_quote(db, shipment)


@router.post("/zone-calculate", response_model=ZoneQuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_zone_quote(
    payload: ZoneQuoteWithNotifyRequest,
    db: Session = Depends(get_db),
) -> ZoneQuoteResult:
    _validate_quote_request(payload.quote)
    return calculate_zone_quote_service(
        db,
        payload.quote,
        notify_email=payload.notify_email,
        email_config_id=payload.email_config_id,
        notify_wecom=payload.notify_wecom,
        wecom_bot_id=payload.wecom_bot_id,
    )


@router.post(
    "/zone-preview",
    response_model=ZoneQuotePreviewResponse,
    responses={
        401: {"description": "X-API-Key is missing or invalid."},
        403: {"description": "API key role, scope, or tenant is not allowed."},
        422: {"description": "The request context is invalid."},
        503: {
            "description": "The authoritative quote release is unavailable or changed.",
            "model": ZoneQuotePreviewResponse,
        },
    },
)
def preview_zone_quote(
    payload: ZoneQuotePreviewRequest,
    actor: CurrentActor = Depends(
        require_roles(
            *QUOTE_WRITE_ROLES,
            update_api_key_last_used=False,
            required_scope="quote:preview",
            api_key_only=True,
        )
    ),
    db: Session = Depends(get_db),
) -> ZoneQuotePreviewResponse | JSONResponse:
    _validate_quote_request(payload.quote)
    requested_origin = _validate_preview_origin(payload)
    if actor.api_key_id is not None and actor.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key tenant does not match request.")

    source_status, result, reasons = calculate_zone_quote_preview_service(
        db,
        payload.quote,
        origin=requested_origin,
        effective_date=payload.effective_date,
    )
    if "effective_date_outside_release_window" in reasons:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="effective_date is outside the active release window.",
        )
    response = _build_zone_preview_response(
        source_status,
        result,
        reasons,
        requested_origin,
        quote=payload.quote,
        tenant=payload.tenant_id,
        effective_date=payload.effective_date,
    )
    if response.status == "unavailable":
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))
    return response


def _validate_quote_request(payload: ZoneQuoteRequest) -> None:
    try:
        validate_zone_quote_request(payload)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


def _validate_preview_origin(payload: ZoneQuotePreviewRequest) -> str:
    requested_origin = payload.origin
    if requested_origin not in {"toronto", "calgary"}:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="origin is not supported.")
    return requested_origin


def _build_zone_preview_response(
    source_status: SourceStatus,
    result: ZoneQuoteResult | None,
    reasons: list[str],
    requested_origin: str,
    *,
    quote: ZoneQuoteRequest,
    tenant: str,
    effective_date: date,
) -> ZoneQuotePreviewResponse:
    source_ref_ids = []
    ready = source_status.ready and not source_status.test_data
    if result is None:
        return ZoneQuotePreviewResponse(
            quote_id=None,
            quote_version=None,
            status="unavailable",
            source_type="manual_required",
            origin=requested_origin,
            zone=None,
            billing_pallets=None,
            fees={},
            test_data=source_status.test_data,
            manual_review_required=True,
            matched_by=None,
            rule_version=source_status.rule_version,
            data_version=source_status.data_version,
            valid_from=source_status.valid_from,
            valid_to=source_status.valid_to,
            source_ref=None,
            service_version=source_status.service_version,
            contract_version=PREVIEW_CONTRACT_VERSION,
            release_id=source_status.release_id,
            release_hash=source_status.release_hash,
            snapshot_hash=source_status.snapshot_hash,
            published_at=source_status.published_at,
            reasons=reasons,
            quote_status="not_calculable",
            currency="USD",
            total=None,
            line_items=[],
            source_ref_ids=source_ref_ids,
            sendable=False,
            tenant=tenant,
            effective_date=effective_date.isoformat(),
            ready=False,
        )

    has_price = not result.manual_review_required and result.total_price_usd is not None
    fees = _preview_fees(result) if has_price else {}
    status = "quoted" if has_price else "manual_required"
    source_ref_ids = _preview_source_ref_ids(source_status)
    total = (
        ZoneQuotePreviewFee(amount=_decimal_string(result.total_price_usd))
        if has_price and result.total_price_usd is not None
        else None
    )
    line_items = _preview_line_items(result, source_ref_ids) if has_price else []
    return ZoneQuotePreviewResponse(
        quote_id=_preview_quote_id(
            quote,
            tenant=tenant,
            origin=requested_origin,
            effective_date=effective_date,
            source_status=source_status,
        ),
        quote_version=quote_version(source_status),
        status=status,
        source_type=result.source_type.value,
        origin=result.origin,
        zone=result.zone,
        billing_pallets=result.billing_pallets,
        fees=fees,
        test_data=source_status.test_data,
        manual_review_required=not has_price,
        matched_by=result.matched_by,
        rule_version=source_status.rule_version,
        data_version=source_status.data_version,
        valid_from=source_status.valid_from,
        valid_to=source_status.valid_to,
        source_ref=_source_ref(result.source_type.value) or (source_ref_ids[0] if source_ref_ids else None),
        service_version=source_status.service_version,
        contract_version=PREVIEW_CONTRACT_VERSION,
        release_id=source_status.release_id,
        release_hash=source_status.release_hash,
        snapshot_hash=source_status.snapshot_hash,
        published_at=source_status.published_at,
        reasons=reasons or sorted(result.risk_tags),
        quote_status="calculated" if has_price else "manual_review",
        currency="USD",
        total=total,
        line_items=line_items,
        source_ref_ids=source_ref_ids,
        sendable=False,
        tenant=tenant,
        effective_date=effective_date.isoformat(),
        ready=ready,
    )


def _preview_source_ref_ids(source_status: SourceStatus) -> list[str]:
    digest = (source_status.snapshot_hash or "").removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return []
    return [f"src:quote:snapshot:{digest}"]


def _preview_quote_id(
    quote: ZoneQuoteRequest,
    *,
    tenant: str,
    origin: str,
    effective_date: date,
    source_status: SourceStatus,
) -> str:
    canonical = {
        "tenant": tenant,
        "origin": origin,
        "effective_date": effective_date.isoformat(),
        "quote": quote.model_dump(mode="json"),
        "quote_version": quote_version(source_status),
        "release_id": source_status.release_id,
        "release_hash": source_status.release_hash,
        "snapshot_hash": source_status.snapshot_hash,
    }
    encoded = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"preview:{sha256(encoded).hexdigest()}"


def _preview_line_items(result: ZoneQuoteResult, source_ref_ids: list[str]) -> list[ZoneQuotePreviewLineItem]:
    items: list[ZoneQuotePreviewLineItem] = []
    if result.base_price_usd is not None:
        items.append(
            ZoneQuotePreviewLineItem(
                line_id="zone_base",
                label="Canada final-mile base price",
                amount=ZoneQuotePreviewFee(amount=_decimal_string(result.base_price_usd)),
                pricing_basis="zone_price_matrix",
                source_ref_ids=list(source_ref_ids),
            )
        )
    for index, (name, value) in enumerate({"fuel": result.fuel_usd, **result.accessorials}.items(), start=1):
        if value is None:
            continue
        items.append(
            ZoneQuotePreviewLineItem(
                line_id=f"zone_fee_{index}",
                label=name,
                amount=ZoneQuotePreviewFee(amount=_decimal_string(value)),
                pricing_basis="zone_pricing_config",
                source_ref_ids=list(source_ref_ids),
            )
        )
    return items


def _preview_fees(result: ZoneQuoteResult) -> dict[str, ZoneQuotePreviewFee]:
    values: dict[str, Decimal | None] = {
        "base": result.base_price_usd,
        "fuel": result.fuel_usd,
        **result.accessorials,
        "total": result.total_price_usd,
    }
    return {
        name: ZoneQuotePreviewFee(amount=_decimal_string(value))
        for name, value in values.items()
        if value is not None
    }


def _decimal_string(value: Decimal) -> str:
    try:
        return f"{Decimal(str(value)).quantize(Decimal('0.01')):.2f}"
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("Quote fee is not a valid decimal.") from exc


def _source_ref(source_type: str) -> str | None:
    return {
        "zone_matrix": "zone_price_matrix",
        "learned_manual_quote": "learned_quote_rules",
    }.get(source_type)
