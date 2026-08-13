from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Literal

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
)
from apps.api.services.source_status_service import SourceStatus, quote_version
from packages.quote_engine.models import QuoteResult, ShipmentInput
from packages.quote_engine.zone_lookup import normalize_origin
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])


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

    tenant_id: str = Field(min_length=1, max_length=128)
    origin: str = Field(min_length=1, max_length=32)
    effective_date: date
    quote: ZoneQuoteRequest

    @model_validator(mode="before")
    @classmethod
    def wrap_flat_quote(cls, value: object) -> object:
        if isinstance(value, dict) and "quote" not in value:
            return {"quote": value}
        return value


class ZoneQuotePreviewFee(BaseModel):
    model_config = ConfigDict(extra="forbid")

    amount: str = Field(pattern=r"^\d+\.\d{2}$")
    currency: Literal["USD"] = "USD"


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


@router.post("/calculate", response_model=QuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_quote(shipment: ShipmentInput, db: Session = Depends(get_db)) -> QuoteResult:
    return calculate_vendor_quote(db, shipment)


@router.post("/zone-calculate", response_model=ZoneQuoteResult, dependencies=[Depends(require_roles(*QUOTE_WRITE_ROLES))])
def calculate_zone_quote(
    payload: ZoneQuoteWithNotifyRequest,
    db: Session = Depends(get_db),
) -> ZoneQuoteResult:
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
        503: {"description": "The authoritative quote release is unavailable or changed."},
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
    requested_origin = normalize_origin(payload.origin)
    if requested_origin is None:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="origin is not supported.")
    if payload.effective_date != date.today():
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="effective_date is limited to the current active rules.",
        )
    if actor.api_key_id is not None and actor.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key tenant does not match request.")

    source_status, result, reasons = calculate_zone_quote_preview_service(
        db,
        payload.quote,
        origin=requested_origin,
    )
    response = _build_zone_preview_response(source_status, result, reasons, requested_origin)
    if response.status == "unavailable":
        return JSONResponse(status_code=503, content=response.model_dump(mode="json"))
    return response


def _build_zone_preview_response(
    source_status: SourceStatus,
    result: ZoneQuoteResult | None,
    reasons: list[str],
    requested_origin: str,
) -> ZoneQuotePreviewResponse:
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
            contract_version=source_status.contract_version,
            release_id=source_status.release_id,
            release_hash=source_status.release_hash,
            snapshot_hash=source_status.snapshot_hash,
            published_at=source_status.published_at,
            reasons=reasons,
        )

    has_price = not result.manual_review_required and result.total_price_usd is not None
    fees = _preview_fees(result) if has_price else {}
    status = "quoted" if has_price else "manual_required"
    return ZoneQuotePreviewResponse(
        quote_id=result.quote_id,
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
        source_ref=_source_ref(result.source_type.value),
        service_version=source_status.service_version,
        contract_version=source_status.contract_version,
        release_id=source_status.release_id,
        release_hash=source_status.release_hash,
        snapshot_hash=source_status.snapshot_hash,
        published_at=source_status.published_at,
        reasons=reasons or sorted(result.risk_tags),
    )


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
