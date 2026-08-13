import json
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from typing import Annotated, Literal, Union

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, model_validator
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
from packages.quote_engine.zone_lookup import normalize_origin
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


router = APIRouter(prefix="/quotes", tags=["quotes"])
SourceRefId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")]
V2Identifier = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")]
V2Version = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$")]
V2Hash = Annotated[str, Field(pattern=r"^sha256:[A-Fa-f0-9]{64}$")]
_DECIMAL_STRING_RE = re.compile(r"^(?:0|[1-9]\d*)(?:\.\d+)?$")
_PREVIEW_DECIMAL_LIMITS = {
    "cbm": (Decimal("1000"), 3),
    "weight_kg": (Decimal("100000"), 3),
    "longest_side_cm": (Decimal("10000"), 2),
}
_PREVIEW_DECIMAL_MAX_DIGITS = 12
_PREVIEW_DECIMAL_MAX_LENGTH = 24


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


class ZoneQuotePreviewQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address_line: StrictStr | None = None
    postal_code: StrictStr
    city: StrictStr | None = None
    province: StrictStr | None = None
    cbm: StrictStr = Field(
        pattern=_DECIMAL_STRING_RE.pattern,
        max_length=_PREVIEW_DECIMAL_MAX_LENGTH,
        json_schema_extra={"x-decimal-maximum": "1000", "x-decimal-places": 3},
    )
    weight_kg: StrictStr = Field(
        pattern=_DECIMAL_STRING_RE.pattern,
        max_length=_PREVIEW_DECIMAL_MAX_LENGTH,
        json_schema_extra={"x-decimal-maximum": "100000", "x-decimal-places": 3},
    )
    piece_count: StrictInt = Field(ge=1)
    packaging_type: StrictStr
    longest_side_cm: StrictStr = Field(
        pattern=_DECIMAL_STRING_RE.pattern,
        max_length=_PREVIEW_DECIMAL_MAX_LENGTH,
        json_schema_extra={"x-decimal-maximum": "10000", "x-decimal-places": 2},
    )
    address_type: StrictStr
    requires_liftgate: StrictBool
    requires_pallet_jack: StrictBool
    requires_appointment: StrictBool
    explicit_pallet_count: StrictInt | None = Field(..., ge=1)
    is_stackable: StrictBool
    detention_minutes: StrictInt = Field(ge=0)

    @model_validator(mode="after")
    def validate_preview_values(self):
        for field, (maximum, decimal_places) in _PREVIEW_DECIMAL_LIMITS.items():
            raw_value = getattr(self, field)
            if len(raw_value) > _PREVIEW_DECIMAL_MAX_LENGTH or _DECIMAL_STRING_RE.fullmatch(raw_value) is None:
                raise ValueError(f"{field} must be a decimal string")
            try:
                value_as_decimal = Decimal(raw_value)
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise ValueError(f"{field} must be greater than zero for preview") from exc
            integer_part, _, fractional_part = raw_value.partition(".")
            if (
                len(integer_part) + len(fractional_part) > _PREVIEW_DECIMAL_MAX_DIGITS
                or len(fractional_part) > decimal_places
                or not value_as_decimal.is_finite()
                or value_as_decimal <= 0
                or value_as_decimal > maximum
            ):
                raise ValueError(f"{field} must be greater than zero for preview")
        if self.explicit_pallet_count is not None and self.explicit_pallet_count < 1:
            raise ValueError("explicit_pallet_count must be null or at least one for preview")
        return self


class ZoneQuotePreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tenant_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    origin: str = Field(min_length=1, max_length=32)
    effective_date: date
    quote: ZoneQuotePreviewQuoteRequest

    @model_validator(mode="before")
    @classmethod
    def require_date_string(cls, value: object) -> object:
        if isinstance(value, dict):
            for field in ("tenant_id", "origin"):
                if field in value and not isinstance(value[field], str):
                    raise ValueError(f"{field} must be a string")
            if "effective_date" in value and not (
                isinstance(value["effective_date"], str)
                and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["effective_date"])
            ):
                raise ValueError("effective_date must be an ISO YYYY-MM-DD string")
        return value

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


class ZoneQuotePreviewLineItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    line_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")
    label: str = Field(min_length=1, max_length=200)
    amount: ZoneQuotePreviewFee
    pricing_basis: str = Field(min_length=1, max_length=500)
    source_ref_ids: list[SourceRefId] = Field(min_length=1)


class _ZoneQuotePreviewAvailableBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["quote-result@2026-08-13.v2"]
    quote_id: V2Identifier
    quote_version: V2Version
    status: Literal["quoted", "manual_required"]
    source_type: V2Identifier
    origin: V2Identifier
    zone: int | None
    billing_pallets: int | None
    fees: dict[str, ZoneQuotePreviewFee]
    test_data: Literal[False]
    manual_review_required: bool
    matched_by: str | None
    rule_version: V2Version
    data_version: V2Version
    valid_from: date
    valid_to: date
    source_ref: V2Identifier | None
    service_version: V2Version
    contract_version: Literal["quote-zone.v2"]
    release_id: V2Identifier
    release_hash: V2Hash
    snapshot_hash: V2Hash
    published_at: AwareDatetime
    reasons: list[str]
    currency: Literal["USD"]
    source_ref_ids: list[SourceRefId] = Field(min_length=1)
    sendable: Literal[False]
    tenant: V2Identifier
    effective_date: date
    ready: Literal[True]

    @model_validator(mode="after")
    def validate_release_identity(self):
        if self.release_hash != self.snapshot_hash:
            raise ValueError("release_hash must equal snapshot_hash")
        expected_quote_version = f"{self.release_id}:{self.rule_version}:{self.data_version}"
        if self.quote_version != expected_quote_version:
            raise ValueError("quote_version must equal release_id:rule_version:data_version")
        if self.valid_from > self.valid_to or not self.valid_from <= self.effective_date <= self.valid_to:
            raise ValueError("effective_date must be within the valid release window")
        if len(set(self.source_ref_ids)) != len(self.source_ref_ids):
            raise ValueError("source_ref_ids must be unique")
        return self


class ZoneQuotePreviewCalculatedResponse(_ZoneQuotePreviewAvailableBase):
    status: Literal["quoted"]
    manual_review_required: Literal[False]
    quote_status: Literal["calculated"]
    total: ZoneQuotePreviewFee
    line_items: list[ZoneQuotePreviewLineItem] = Field(min_length=1)
    billing_pallets: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_line_items(self):
        if self.status != "quoted" or self.manual_review_required:
            raise ValueError("calculated response must be quoted and not require manual review")
        line_ids = [item.line_id for item in self.line_items]
        if len(line_ids) != len(set(line_ids)):
            raise ValueError("calculated line_ids must be unique")
        expected_refs = set(self.source_ref_ids)
        if any(set(item.source_ref_ids) != expected_refs for item in self.line_items):
            raise ValueError("line item source_ref_ids must equal top-level source_ref_ids")
        total = Decimal(self.total.amount)
        amount_sum = sum((Decimal(item.amount.amount) for item in self.line_items), Decimal("0"))
        if amount_sum != total:
            raise ValueError("line item amounts must equal total")
        return self


class ZoneQuotePreviewManualResponse(_ZoneQuotePreviewAvailableBase):
    status: Literal["manual_required"]
    manual_review_required: Literal[True]
    quote_status: Literal["manual_review", "not_calculable"]
    total: Literal[None] = None
    line_items: list[ZoneQuotePreviewLineItem] = Field(default_factory=list, max_length=0)
    billing_pallets: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_manual_status(self):
        if self.status != "manual_required" or not self.manual_review_required:
            raise ValueError("manual response must require manual review")
        return self


ZoneQuotePreviewResponse = Annotated[
    Union[ZoneQuotePreviewCalculatedResponse, ZoneQuotePreviewManualResponse],
    Field(discriminator="quote_status"),
]


class ZoneQuotePreviewUnavailableResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: Literal["quote-preview-unavailable@2026-08-13"]
    quote_id: Literal[None] = None
    quote_version: Literal[None] = None
    status: Literal["unavailable"]
    source_type: Literal["manual_required"]
    origin: V2Identifier
    zone: Literal[None] = None
    billing_pallets: Literal[None] = None
    fees: dict[str, ZoneQuotePreviewFee] = Field(default_factory=dict, max_length=0)
    test_data: bool
    manual_review_required: Literal[True]
    matched_by: Literal[None] = None
    rule_version: V2Version | None
    data_version: V2Version | None
    valid_from: date | None
    valid_to: date | None
    source_ref: Literal[None] = None
    service_version: V2Version | None
    contract_version: Literal["quote-zone.v2"]
    release_id: V2Identifier | None
    release_hash: V2Hash | None
    snapshot_hash: V2Hash | None
    published_at: AwareDatetime | None
    reasons: list[str] = Field(min_length=1)
    quote_status: Literal["not_calculable"]
    total: Literal[None] = None
    line_items: list[ZoneQuotePreviewLineItem] = Field(default_factory=list, max_length=0)
    source_ref_ids: list[SourceRefId] = Field(default_factory=list, max_length=0)
    sendable: Literal[False]
    tenant: V2Identifier
    effective_date: date
    ready: Literal[False]


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
            "model": ZoneQuotePreviewUnavailableResponse,
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
) -> ZoneQuotePreviewResponse | ZoneQuotePreviewUnavailableResponse | JSONResponse:
    quote = _preview_legacy_quote(payload.quote)
    _validate_quote_request(quote)
    requested_origin = _validate_preview_origin(payload)
    if actor.api_key_id is not None and actor.tenant_id != payload.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="API key tenant does not match request.")

    source_status, result, reasons = calculate_zone_quote_preview_service(
        db,
        quote,
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
        quote=quote,
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


def _preview_legacy_quote(payload: ZoneQuotePreviewQuoteRequest) -> ZoneQuoteRequest:
    try:
        return ZoneQuoteRequest.model_validate(payload.model_dump())
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
) -> ZoneQuotePreviewCalculatedResponse | ZoneQuotePreviewManualResponse | ZoneQuotePreviewUnavailableResponse:
    source_ref_ids = _preview_source_ref_ids(source_status)
    if result is None or not source_status.ready or source_status.test_data or not source_ref_ids:
        unavailable_reasons = list(reasons)
        if not unavailable_reasons:
            unavailable_reasons.append("quote_preview_unavailable")
        if not source_ref_ids and result is not None:
            unavailable_reasons.append("quote_preview_source_ref_missing")
        return _unavailable_zone_preview_response(
            source_status,
            unavailable_reasons,
            requested_origin,
            tenant=tenant,
            effective_date=effective_date,
        )

    raw_result_origin = result.origin
    normalized_result_origin = normalize_origin(raw_result_origin) if raw_result_origin is not None else None
    origin_mismatch = raw_result_origin is not None and normalized_result_origin != requested_origin
    if origin_mismatch:
        return _unavailable_zone_preview_response(
            source_status,
            [*reasons, "origin_mismatch"],
            requested_origin,
            tenant=tenant,
            effective_date=effective_date,
        )
    response_origin = requested_origin
    response_quote_version = quote_version(source_status)
    if response_quote_version is None:
        return _build_zone_preview_response(
            source_status,
            None,
            [*reasons, "quote_preview_identity_missing"],
            requested_origin,
            quote=quote,
            tenant=tenant,
            effective_date=effective_date,
        )

    has_price = (
        not origin_mismatch
        and not result.manual_review_required
        and result.total_price_usd is not None
        and _preview_monetary_values_are_safe(result)
    )
    if has_price:
        try:
            total = ZoneQuotePreviewFee(amount=_decimal_string(result.total_price_usd))
            line_items = _preview_line_items(result, source_ref_ids)
            calculated = ZoneQuotePreviewCalculatedResponse(
                version="quote-result@2026-08-13.v2",
                quote_id=_preview_quote_id(
                    quote,
                    tenant=tenant,
                    origin=requested_origin,
                    effective_date=effective_date,
                    source_status=source_status,
                ),
                quote_version=response_quote_version,
                status="quoted",
                source_type=result.source_type.value,
                origin=response_origin,
                zone=result.zone,
                billing_pallets=result.billing_pallets,
                fees=_preview_fees(result),
                test_data=False,
                manual_review_required=False,
                matched_by=result.matched_by,
                rule_version=source_status.rule_version,
                data_version=source_status.data_version,
                valid_from=source_status.valid_from,
                valid_to=source_status.valid_to,
                source_ref=_source_ref(result.source_type.value) or source_ref_ids[0],
                service_version=source_status.service_version,
                contract_version=PREVIEW_CONTRACT_VERSION,
                release_id=source_status.release_id,
                release_hash=source_status.release_hash,
                snapshot_hash=source_status.snapshot_hash,
                published_at=source_status.published_at,
                reasons=reasons or sorted(result.risk_tags),
                quote_status="calculated",
                currency="USD",
                total=total,
                line_items=line_items,
                source_ref_ids=source_ref_ids,
                sendable=False,
                tenant=tenant,
                effective_date=effective_date,
                ready=True,
            )
            return calculated
        except (InvalidOperation, TypeError, ValueError):
            pass

    manual_reasons = list(reasons or sorted(result.risk_tags))
    if not _preview_monetary_values_are_safe(result) or not result.manual_review_required:
        manual_reasons.append("quote_preview_invariant_failed")
    return ZoneQuotePreviewManualResponse(
        version="quote-result@2026-08-13.v2",
        quote_id=_preview_quote_id(
            quote,
            tenant=tenant,
            origin=requested_origin,
            effective_date=effective_date,
            source_status=source_status,
        ),
        quote_version=response_quote_version,
        status="manual_required",
        source_type=result.source_type.value,
        origin=response_origin,
        zone=result.zone,
        billing_pallets=result.billing_pallets if result.billing_pallets and result.billing_pallets >= 1 else None,
        fees={},
        test_data=False,
        manual_review_required=True,
        matched_by=result.matched_by,
        rule_version=source_status.rule_version,
        data_version=source_status.data_version,
        valid_from=source_status.valid_from,
        valid_to=source_status.valid_to,
        source_ref=_source_ref(result.source_type.value) or source_ref_ids[0],
        service_version=source_status.service_version,
        contract_version=PREVIEW_CONTRACT_VERSION,
        release_id=source_status.release_id,
        release_hash=source_status.release_hash,
        snapshot_hash=source_status.snapshot_hash,
        published_at=source_status.published_at,
        reasons=sorted(set(manual_reasons)),
        quote_status="manual_review",
        currency="USD",
        source_ref_ids=source_ref_ids,
        sendable=False,
        tenant=tenant,
        effective_date=effective_date,
        ready=True,
    )


def _unavailable_zone_preview_response(
    source_status: SourceStatus,
    reasons: list[str],
    requested_origin: str,
    *,
    tenant: str,
    effective_date: date,
) -> ZoneQuotePreviewUnavailableResponse:
    return ZoneQuotePreviewUnavailableResponse(
        version="quote-preview-unavailable@2026-08-13",
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
        rule_version=_safe_v2_version(source_status.rule_version),
        data_version=_safe_v2_version(source_status.data_version),
        valid_from=_safe_date(source_status.valid_from),
        valid_to=_safe_date(source_status.valid_to),
        source_ref=None,
        service_version=_safe_v2_version(source_status.service_version),
        contract_version=PREVIEW_CONTRACT_VERSION,
        release_id=_safe_v2_identifier(source_status.release_id),
        release_hash=_safe_v2_hash(source_status.release_hash),
        snapshot_hash=_safe_v2_hash(source_status.snapshot_hash),
        published_at=_safe_aware_datetime(source_status.published_at),
        reasons=sorted(set(reasons or ["quote_preview_unavailable"])),
        quote_status="not_calculable",
        total=None,
        line_items=[],
        source_ref_ids=[],
        sendable=False,
        tenant=tenant,
        effective_date=effective_date,
        ready=False,
    )


def _safe_v2_identifier(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$", value) else None


def _safe_v2_version(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"^[A-Za-z0-9][A-Za-z0-9._:@/-]{0,127}$", value) else None


def _safe_v2_hash(value: object) -> str | None:
    return value if isinstance(value, str) and re.fullmatch(r"^sha256:[A-Fa-f0-9]{64}$", value) else None


def _safe_date(value: object) -> date | None:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return date.fromisoformat(value)
        except ValueError:
            return None
    return None


def _safe_aware_datetime(value: object) -> AwareDatetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        return None
    return parsed


def _preview_source_ref_ids(source_status: SourceStatus) -> list[str]:
    digest = (source_status.snapshot_hash or "").removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        return []
    return [f"src:quote:snapshot:{digest}"]


def _preview_monetary_values_are_safe(result: ZoneQuoteResult) -> bool:
    values = [result.base_price_usd, result.fuel_usd, result.total_price_usd, *result.accessorials.values()]
    if any(value is None for value in values[:3]):
        return False
    try:
        decimals = [Decimal(str(value)) for value in values if value is not None]
    except (InvalidOperation, TypeError, ValueError):
        return False
    return all(value.is_finite() and value >= 0 for value in decimals)


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
