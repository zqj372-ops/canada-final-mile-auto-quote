"""Small, deterministic FCL domain model and pricing engine.

ponytail: keep FCL pricing independent from the existing Zone engine; rate-card
rows are intentionally read as mappings so the engine stays easy to test.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator


FCL_CURRENCIES = ("USD", "CAD", "CNY")
FCL_DISPLAY_MODES = ("both", "quoteOnly", "hiddenIncluded", "hiddenExcluded", "merged")
FCL_UNITS = ("container", "shipment", "piece", "kg", "cbm")
FCL_PRICING_STATUSES = ("auto", "actual", "manual", "quote_required")
FCL_SERVICE_SCOPES = ("port-to-port", "port-to-door")
FCL_CUSTOMER_TYPES = ("importer", "exporter", "platform_seller", "forwarder", "warehouse", "other")
FCL_SPECIAL_ATTRIBUTES = (
    "general_cargo",
    "battery",
    "magnetic",
    "liquid",
    "powder",
    "food",
    "wood",
    "dangerous_goods",
    "branded",
    "reefer",
    "oversized",
)
FCL_SERVICE_STAGES = ("pickup", "ocean", "customs", "warehousing", "delivery", "door_to_door")
FCL_TRADE_TERMS = ("EXW", "FOB", "CFR", "CIF", "DAP", "DDP", "OTHER")
FCL_EXPORT_DECLARATIONS = ("customer", "platform", "pending")
FCL_IMPORTER_EXISTS = ("yes", "no", "unknown")
FCL_BN_RM_STATUSES = ("ready", "applying", "none", "unknown")
FCL_CARM_STATUSES = ("ready", "pending", "unknown")
FCL_BROKER_OPTIONS = ("yes", "need_platform")
FCL_TAX_INCLUDED_OPTIONS = ("yes", "no", "compare")
FCL_PRIORITY_GOALS = ("economy", "speed", "stable", "balanced")
FCL_DEADLINE_STRICTNESS = ("hard", "negotiable", "reference")
FCL_ADDRESS_TYPES = ("commercial", "residential", "amazon", "warehouse")
FCL_WOOD_PACKAGING = ("none", "compliant", "unknown")
FCL_YES_NO_UNKNOWN = ("yes", "no", "unknown")
CENT = Decimal("0.01")
THOUSANDTH = Decimal("0.001")
HUNDREDTH = Decimal("0.01")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def quantity_decimal(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(HUNDREDTH, rounding=ROUND_HALF_UP)


def _validate_enum(value: str | None, allowed: tuple[str, ...], label: str) -> str | None:
    if value is None or value == "":
        return None
    normalized = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    if normalized not in allowed:
        raise ValueError(f"Unsupported {label}: {value}")
    return normalized


def _validate_enum_list(values: list[str], allowed: tuple[str, ...], label: str) -> list[str]:
    result: list[str] = []
    for value in values:
        normalized = _validate_enum(value, allowed, label)
        if normalized is not None and normalized not in result:
            result.append(normalized)
    return result


class FCLContainerInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    container_type: str = Field(min_length=1, max_length=32)
    quantity: int = Field(gt=0, le=10000)


class FCLCargoItem(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=200)
    quantity: int = Field(default=1, gt=0, le=1_000_000)
    length: Decimal | None = Field(default=None, gt=0)
    width: Decimal | None = Field(default=None, gt=0)
    height: Decimal | None = Field(default=None, gt=0)
    dimension_unit: Literal["mm", "cm", "m", "in"] = "cm"
    weight: Decimal | None = Field(default=None, ge=0)
    weight_unit: Literal["g", "kg", "lb"] = "kg"
    weight_kg: Decimal | None = Field(default=None, ge=0)
    total_weight_kg: Decimal | None = Field(default=None, ge=0)
    total_volume_cbm: Decimal | None = Field(default=None, ge=0)


class FCLQuoteDraft(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    customer_name: str | None = Field(default=None, max_length=200)
    customer_type: str | None = Field(default=None, max_length=32)
    pol: str | None = Field(default=None, max_length=64)
    pod: str | None = Field(default=None, max_length=64)
    destination_postal_code: str | None = Field(default=None, max_length=20)
    destination_address: str | None = Field(default=None, max_length=500)
    containers: list[FCLContainerInput] = Field(default_factory=list, max_length=50)
    cargo_name: str | None = Field(default=None, max_length=200)
    cargo_details: str | None = Field(default=None, max_length=500)
    cargo_items: list[FCLCargoItem] = Field(default_factory=list, max_length=200)
    declared_piece_count: int | None = Field(default=None, ge=0, le=1_000_000)
    declared_total_weight_kg: Decimal | None = Field(default=None, ge=0)
    declared_total_volume_cbm: Decimal | None = Field(default=None, ge=0)
    cargo_value: Decimal | None = Field(default=None, ge=0)
    cargo_value_currency: str | None = Field(default=None, max_length=8)
    hs_code: str | None = Field(default=None, max_length=16)
    origin_country: str | None = Field(default=None, max_length=64)
    stackable: bool | None = None
    special_attributes: list[str] = Field(default_factory=list, max_length=30)
    sds_un_info: str | None = Field(default=None, max_length=500)
    wood_packaging: str | None = Field(default=None, max_length=16)
    ready_date: date | None = None
    target_etd: date | None = None
    expected_delivery_date: date | None = None
    deadline_strictness: str | None = Field(default=None, max_length=16)
    acceptable_transit_days: int | None = Field(default=None, ge=0, le=3650)
    carrier: str | None = Field(default=None, max_length=128)
    service_preference: str | None = Field(default=None, max_length=128)
    service_scope: str | None = None
    trade_terms: str | None = Field(default=None, max_length=16)
    export_declaration: str | None = Field(default=None, max_length=16)
    importer_exists: str | None = Field(default=None, max_length=16)
    importer_legal_name: str | None = Field(default=None, max_length=200)
    bn_rm_status: str | None = Field(default=None, max_length=16)
    carm_status: str | None = Field(default=None, max_length=16)
    has_broker: str | None = Field(default=None, max_length=16)
    tax_included: str | None = Field(default=None, max_length=16)
    priority_goal: str | None = Field(default=None, max_length=16)
    address_type: str | None = Field(default=None, max_length=16)
    tail_lift: str | None = Field(default=None, max_length=16)
    appointment_window: str | None = Field(default=None, max_length=200)
    forklift: str | None = Field(default=None, max_length=16)
    platform_warehouse: str | None = Field(default=None, max_length=300)
    declaration_acknowledged: bool | None = None
    notes: str | None = Field(default=None, max_length=5000)
    vessel: str | None = Field(default=None, max_length=128)
    voyage: str | None = Field(default=None, max_length=128)

    @field_validator("customer_type")
    @classmethod
    def validate_customer_type(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_CUSTOMER_TYPES, "customer type")

    @field_validator("special_attributes")
    @classmethod
    def validate_special_attributes(cls, values: list[str]) -> list[str]:
        return _validate_enum_list(values, FCL_SPECIAL_ATTRIBUTES, "special attribute")

    @field_validator("trade_terms")
    @classmethod
    def validate_trade_terms(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = str(value).strip().upper().replace(" ", "_")
        if normalized in {"其他", "OTHERS", "OTHER"}:
            normalized = "OTHER"
        if normalized not in FCL_TRADE_TERMS:
            raise ValueError(f"Unsupported trade terms: {value}")
        return normalized

    @field_validator("export_declaration")
    @classmethod
    def validate_export_declaration(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_EXPORT_DECLARATIONS, "export declaration")

    @field_validator("importer_exists")
    @classmethod
    def validate_importer_exists(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_IMPORTER_EXISTS, "importer exists")

    @field_validator("bn_rm_status")
    @classmethod
    def validate_bn_rm_status(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_BN_RM_STATUSES, "BN/RM status")

    @field_validator("carm_status")
    @classmethod
    def validate_carm_status(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_CARM_STATUSES, "CARM status")

    @field_validator("has_broker")
    @classmethod
    def validate_has_broker(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_BROKER_OPTIONS, "has broker")

    @field_validator("tax_included")
    @classmethod
    def validate_tax_included(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_TAX_INCLUDED_OPTIONS, "tax included")

    @field_validator("priority_goal")
    @classmethod
    def validate_priority_goal(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_PRIORITY_GOALS, "priority goal")

    @field_validator("deadline_strictness")
    @classmethod
    def validate_deadline_strictness(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_DEADLINE_STRICTNESS, "deadline strictness")

    @field_validator("address_type")
    @classmethod
    def validate_address_type(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_ADDRESS_TYPES, "address type")

    @field_validator("wood_packaging")
    @classmethod
    def validate_wood_packaging(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_WOOD_PACKAGING, "wood packaging")

    @field_validator("tail_lift", "forklift")
    @classmethod
    def validate_yes_no_unknown(cls, value: str | None) -> str | None:
        return _validate_enum(value, FCL_YES_NO_UNKNOWN, "yes/no/unknown")

    @field_validator("cargo_value_currency")
    @classmethod
    def validate_cargo_value_currency(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = value.upper().strip()
        if normalized == "RMB":
            normalized = "CNY"
        if normalized not in FCL_CURRENCIES:
            raise ValueError(f"Unsupported cargo value currency: {value}")
        return normalized

    @field_validator("hs_code")
    @classmethod
    def validate_hs_code(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = "".join(character for character in value if character.isdigit())
        if not 6 <= len(normalized) <= 10:
            raise ValueError("HS code must contain 6-10 digits")
        return normalized

    @field_validator("destination_postal_code")
    @classmethod
    def normalize_postal_code(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        return " ".join(value.upper().split())

    @field_validator("service_scope")
    @classmethod
    def validate_service_scope(cls, value: str | None) -> str | None:
        if value is None or value == "":
            return None
        normalized = value.strip().lower().replace(" ", "-")
        aliases = {
            "portport": "port-to-port",
            "doortport": "door-to-port",
            "portdoor": "port-to-door",
            "doordoor": "door-to-door",
            "港到港": "port-to-port",
            "门到港": "door-to-port",
            "港到门": "port-to-door",
            "门到门": "door-to-door",
        }
        normalized = aliases.get(normalized, normalized)
        if normalized not in FCL_SERVICE_SCOPES:
            raise ValueError(f"Unsupported FCL service scope: {value}")
        return normalized


class FCLExchangeRate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    from_currency: str
    to_currency: str
    rate: Decimal = Field(gt=0)
    effective_from: date | None = None
    effective_to: date | None = None

    @field_validator("from_currency", "to_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.upper().strip()
        if normalized == "RMB":
            normalized = "CNY"
        if normalized not in FCL_CURRENCIES:
            raise ValueError(f"Unsupported currency: {value}")
        return normalized


class FCLQuoteConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    markup_percent: Decimal = Field(default=Decimal("0"), ge=0)
    markup_fixed: Decimal = Field(default=Decimal("0"), ge=0)
    default_quote_valid_days: int = Field(default=7, ge=1, le=365)
    required_fields: list[str] = Field(
        default_factory=lambda: [
            "customer_name",
            "contact",
            "customer_type",
            "pol",
            "pod",
            "containers",
            "cargo",
            "service_scope",
            "special_attributes",
            "ready_date",
            "importer_exists",
        ]
    )
    port_aliases: dict[str, str] = Field(default_factory=dict)
    container_aliases: dict[str, str] = Field(default_factory=dict)
    settlement_currency: str | None = None
    exchange_rates: list[FCLExchangeRate] = Field(default_factory=list, max_length=100)
    company_name: str = Field(default="", max_length=200)
    company_address: str = Field(default="", max_length=500)
    company_phone: str = Field(default="", max_length=100)
    company_email: str = Field(default="", max_length=200)
    company_logo: str = Field(default="", max_length=2000)
    terms: list[str] = Field(default_factory=list, max_length=50)
    footer: str = Field(default="", max_length=1000)
    renderer_version: str = Field(default="fcl-html-v1", max_length=64)

    @field_validator("settlement_currency")
    @classmethod
    def validate_settlement_currency(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = value.upper().strip()
        if normalized == "RMB":
            normalized = "CNY"
        if normalized not in FCL_CURRENCIES:
            raise ValueError(f"Unsupported settlement currency: {value}")
        return normalized


class FCLFeeLine(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=500)
    unit: Literal["container", "shipment", "piece", "kg", "cbm"]
    currency: str
    sales_unit_price: Decimal | None = Field(default=None, ge=0)
    cost_unit_price: Decimal | None = Field(default=None, ge=0)
    pricing_status: Literal["auto", "actual", "manual", "quote_required"] = "auto"
    display_mode: Literal["both", "quoteOnly", "hiddenIncluded", "hiddenExcluded", "merged"] = "both"
    include_in_quote: bool = True
    public_note: str = Field(default="", max_length=500)
    vendor: str | None = Field(default=None, max_length=200)
    internal_note: str | None = Field(default=None, max_length=1000)

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.upper().strip()
        if normalized == "RMB":
            normalized = "CNY"
        if normalized not in FCL_CURRENCIES:
            raise ValueError(f"Unsupported currency: {value}")
        return normalized


class FCLRateCardPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    pol: str = Field(min_length=1, max_length=64)
    pod: str = Field(min_length=1, max_length=64)
    container_type: str = Field(min_length=1, max_length=32)
    carrier: str | None = Field(default=None, max_length=128)
    service: str | None = Field(default=None, max_length=128)
    service_scope: str | None = None
    effective_from: date | None = None
    effective_to: date | None = None
    etd_date: date | None = None
    vessel_voyage: str | None = Field(default=None, max_length=128)
    priority: int = Field(default=100, ge=1, le=10000)
    source: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    fee_lines: list[FCLFeeLine] = Field(min_length=1, max_length=100)

    @field_validator("service_scope")
    @classmethod
    def validate_card_scope(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None
        normalized = value.strip().lower().replace(" ", "-")
        if normalized not in FCL_SERVICE_SCOPES:
            raise ValueError(f"Unsupported FCL service scope: {value}")
        return normalized


class FCLCargoCalculation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]] = Field(default_factory=list)
    piece_count: int | None = None
    total_weight_kg: Decimal | None = None
    total_volume_cbm: Decimal | None = None
    declared_piece_count: int | None = None
    declared_total_weight_kg: Decimal | None = None
    declared_total_volume_cbm: Decimal | None = None
    conflicts: list[str] = Field(default_factory=list)
    calculation_basis: list[str] = Field(default_factory=list)


class FCLFeeItemPublic(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_name: str
    description: str
    quantity: Decimal
    unit: str
    unit_price: Decimal | None
    amount: Decimal | None
    currency: str
    pricing_status: str
    display_mode: str
    included: bool
    public_note: str


class FCLQuoteResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    quote_id: str
    quote_type: Literal["fcl"] = "fcl"
    source_type: str
    normalized_input: FCLQuoteDraft
    cargo_calculation: FCLCargoCalculation
    matched_rate_cards: list[dict[str, Any]] = Field(default_factory=list)
    fee_items: list[FCLFeeItemPublic] = Field(default_factory=list)
    totals_by_currency: dict[str, Decimal] = Field(default_factory=dict)
    settlement_currency: str | None = None
    converted_total: Decimal | None = None
    exchange_snapshot: list[dict[str, Any]] = Field(default_factory=list)
    quote_valid_until: date | None = None
    public_terms: list[str] = Field(default_factory=list)
    company_name: str = ""
    company_address: str = ""
    company_phone: str = ""
    company_email: str = ""
    company_logo: str = ""
    footer: str = ""
    renderer_version: str
    manual_review_required: bool
    manual_reasons: list[str] = Field(default_factory=list)
    customer_reply: str | None = None


def default_fcl_quote_config() -> FCLQuoteConfig:
    return FCLQuoteConfig()


def normalize_port(value: str | None, aliases: Mapping[str, str] | None = None) -> str | None:
    if not value:
        return None
    compact = " ".join(str(value).upper().replace("–", "-").split())
    alias_map = {normalize_key(key): normalize_key(alias) for key, alias in (aliases or {}).items()}
    return alias_map.get(normalize_key(compact), normalize_key(compact))


def normalize_container_type(value: str, aliases: Mapping[str, str] | None = None) -> str:
    normalized = normalize_key(value).replace(" ", "")
    alias_map = {normalize_key(key).replace(" ", ""): normalize_key(alias).replace(" ", "") for key, alias in (aliases or {}).items()}
    normalized = alias_map.get(normalized, normalized)
    built_in = {
        "20DC": "20GP",
        "20DV": "20GP",
        "40DC": "40GP",
        "40HC": "40HQ",
        "40HIGHCUBE": "40HQ",
    }
    return built_in.get(normalized, normalized)


def normalize_key(value: str) -> str:
    return " ".join(str(value).upper().replace("_", " ").split())


def calculate_cargo(draft: FCLQuoteDraft) -> FCLCargoCalculation:
    conflicts: list[str] = []
    items: list[dict[str, Any]] = []
    computed_weight = Decimal("0")
    computed_volume = Decimal("0")
    computed_weight_available = False
    computed_volume_available = False

    for index, item in enumerate(draft.cargo_items, start=1):
        per_piece_weight: Decimal | None = item.weight_kg
        if per_piece_weight is None and item.weight is not None:
            per_piece_weight = item.weight * {"g": Decimal("0.001"), "kg": Decimal("1"), "lb": Decimal("0.45359237")} [item.weight_unit]
        total_weight = item.total_weight_kg
        if per_piece_weight is not None:
            calculated_total_weight = per_piece_weight * item.quantity
            if total_weight is not None and abs(total_weight - calculated_total_weight) > Decimal("0.01"):
                conflicts.append(f"cargo_items[{index}].weight_conflict")
            total_weight = calculated_total_weight
            computed_weight += calculated_total_weight
            computed_weight_available = True

        total_volume = item.total_volume_cbm
        if item.length is not None and item.width is not None and item.height is not None:
            factor = {"mm": Decimal("0.001"), "cm": Decimal("0.01"), "m": Decimal("1"), "in": Decimal("0.0254")} [item.dimension_unit]
            per_piece_volume = item.length * factor * item.width * factor * item.height * factor
            calculated_total_volume = per_piece_volume * item.quantity
            if total_volume is not None and abs(total_volume - calculated_total_volume) > Decimal("0.000001"):
                conflicts.append(f"cargo_items[{index}].volume_conflict")
            total_volume = calculated_total_volume
            computed_volume += calculated_total_volume
            computed_volume_available = True

        items.append(
            {
                "name": item.name,
                "quantity": item.quantity,
                "length": str(item.length) if item.length is not None else None,
                "width": str(item.width) if item.width is not None else None,
                "height": str(item.height) if item.height is not None else None,
                "dimension_unit": item.dimension_unit,
                "weight_kg": str(per_piece_weight.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)) if per_piece_weight is not None else None,
                "total_weight_kg": str(total_weight.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)) if total_weight is not None else None,
                "total_volume_cbm": str(total_volume.quantize(THOUSANDTH, rounding=ROUND_HALF_UP)) if total_volume is not None else None,
            }
        )

    piece_count = sum(item.quantity for item in draft.cargo_items) if draft.cargo_items else draft.declared_piece_count
    total_weight = computed_weight.quantize(HUNDREDTH, rounding=ROUND_HALF_UP) if computed_weight_available else draft.declared_total_weight_kg
    total_volume = computed_volume.quantize(THOUSANDTH, rounding=ROUND_HALF_UP) if computed_volume_available else draft.declared_total_volume_cbm

    if draft.declared_piece_count is not None and piece_count is not None and draft.cargo_items and draft.declared_piece_count != piece_count:
        conflicts.append("declared_piece_count_conflict")
    if computed_weight_available and draft.declared_total_weight_kg is not None and abs(draft.declared_total_weight_kg - computed_weight) > Decimal("0.01"):
        conflicts.append("declared_total_weight_conflict")
    if computed_volume_available and draft.declared_total_volume_cbm is not None and abs(draft.declared_total_volume_cbm - computed_volume) > Decimal("0.000001"):
        conflicts.append("declared_total_volume_conflict")

    basis: list[str] = []
    if computed_weight_available:
        basis.append("weight_from_items")
    elif draft.declared_total_weight_kg is not None:
        basis.append("declared_total_weight")
    if computed_volume_available:
        basis.append("volume_from_dimensions")
    elif draft.declared_total_volume_cbm is not None:
        basis.append("declared_total_volume")

    return FCLCargoCalculation(
        items=items,
        piece_count=piece_count,
        total_weight_kg=total_weight,
        total_volume_cbm=total_volume,
        declared_piece_count=draft.declared_piece_count,
        declared_total_weight_kg=draft.declared_total_weight_kg,
        declared_total_volume_cbm=draft.declared_total_volume_cbm,
        conflicts=sorted(set(conflicts)),
        calculation_basis=basis,
    )


def calculate_fcl_quote(
    draft: FCLQuoteDraft,
    config: FCLQuoteConfig,
    rate_cards: list[Mapping[str, Any]],
    *,
    quote_id: str,
    config_version: int,
    quote_date: date | None = None,
) -> tuple[FCLQuoteResult, dict[str, Any]]:
    pricing_date = quote_date or date.today()
    pol = normalize_port(draft.pol, config.port_aliases)
    pod = normalize_port(draft.pod, config.port_aliases)
    normalized_containers: list[FCLContainerInput] = []
    quantities: dict[str, int] = defaultdict(int)
    for container in draft.containers:
        container_type = normalize_container_type(container.container_type, config.container_aliases)
        quantities[container_type] += container.quantity
    for container_type, quantity in quantities.items():
        normalized_containers.append(FCLContainerInput(container_type=container_type, quantity=quantity))
    normalized = draft.model_copy(update={"pol": pol, "pod": pod, "containers": normalized_containers})
    cargo = calculate_cargo(normalized)
    reasons = list(cargo.conflicts)
    missing = _missing_fields(normalized, config.required_fields, cargo)
    reasons.extend(f"missing:{field}" for field in missing)
    if pol and pod and pol == pod:
        reasons.append("pol_pod_must_differ")
    if normalized.deadline_strictness == "hard":
        reasons.append("hard_deadline_manual_review")
    if normalized.importer_exists in ("no", "unknown"):
        reasons.append("importer_condition_manual_review")
    if normalized.wood_packaging == "unknown":
        reasons.append("wood_packaging_pending")
    if normalized.export_declaration == "pending":
        reasons.append("export_declaration_pending")
    if normalized.stackable is False:
        reasons.append("non_stackable_manual_review")

    public_cards: list[dict[str, Any]] = []
    internal_cards: list[dict[str, Any]] = []
    fee_items: list[FCLFeeItemPublic] = []
    internal_fee_items: list[dict[str, Any]] = []
    totals: dict[str, Decimal] = defaultdict(Decimal)

    if not reasons:
        for container_type, container_quantity in quantities.items():
            card, card_reason = _select_rate_card(
                normalized,
                container_type,
                pricing_date,
                rate_cards,
            )
            if card is None:
                reasons.append(card_reason or f"no_published_rate_card:{container_type}")
                continue
            card_data = _card_dict(card)
            card_payload = _validate_rate_card(card_data)
            if card_payload is None:
                reasons.append(f"invalid_rate_card:{card_data.get('id', 'unknown')}")
                continue
            public_cards.append(_public_rate_card(card_data, card_payload))
            internal_cards.append(card_data)
            for raw_line in card_payload.fee_lines:
                quantity = _line_quantity(raw_line.unit, container_quantity, cargo)
                if quantity is None:
                    reasons.append(f"missing_quantity:{raw_line.item_name}")
                    continue
                unit_price = _resolve_unit_price(raw_line, config)
                amount: Decimal | None = None
                included = raw_line.include_in_quote and raw_line.display_mode != "hiddenExcluded"
                if raw_line.pricing_status != "auto":
                    reasons.append(f"manual_fee:{raw_line.item_name}")
                if raw_line.pricing_status == "auto":
                    if unit_price is None:
                        reasons.append(f"missing_price:{raw_line.item_name}")
                    elif included:
                        amount = money(unit_price * quantity)
                        totals[raw_line.currency] += amount
                internal_fee_items.append(
                    {
                        **raw_line.model_dump(mode="json"),
                        "quantity": str(quantity),
                        "unit_price": str(money(unit_price)) if unit_price is not None else None,
                        "amount": str(amount) if amount is not None else None,
                        "container_type": container_type,
                        "rate_card_id": card_data.get("id"),
                    }
                )
                is_visible = raw_line.display_mode in ("both", "quoteOnly", "merged")
                fee_items.append(
                    FCLFeeItemPublic(
                        item_name=raw_line.item_name,
                        description=raw_line.description,
                        quantity=quantity,
                        unit=raw_line.unit,
                        unit_price=money(unit_price) if is_visible and raw_line.pricing_status == "auto" and unit_price is not None else None,
                        amount=amount if is_visible else None,
                        currency=raw_line.currency,
                        pricing_status=raw_line.pricing_status,
                        display_mode=raw_line.display_mode,
                        included=included,
                        public_note=raw_line.public_note,
                    )
                )

    if fee_items and not any(item.amount is not None for item in fee_items):
        reasons.append("no_automatic_fee_total")

    exchange_snapshot: list[dict[str, Any]] = []
    settlement_currency = config.settlement_currency
    converted_total: Decimal | None = None
    if settlement_currency and not reasons:
        converted = Decimal("0")
        for currency, amount in totals.items():
            if currency == settlement_currency:
                converted += amount
                continue
            rate = _find_exchange_rate(config.exchange_rates, currency, settlement_currency, pricing_date)
            if rate is None:
                reasons.append(f"exchange_rate_missing_or_expired:{currency}->{settlement_currency}")
                continue
            converted += amount * rate.rate
            exchange_snapshot.append(rate.model_dump(mode="json"))
        if not reasons:
            converted_total = money(converted)

    normalized_totals = {currency: money(amount) for currency, amount in sorted(totals.items())}
    if reasons:
        fee_items = [item.model_copy(update={"unit_price": None, "amount": None}) for item in fee_items]
        normalized_totals = {}
        converted_total = None

    included_names = [item.item_name for item in fee_items if item.included]
    excluded_names = [item.item_name for item in fee_items if not item.included or item.display_mode == "hiddenExcluded"]
    terms = list(config.terms)
    if included_names:
        terms.insert(0, f"费用包含：{'、'.join(dict.fromkeys(included_names))}。")
    if excluded_names:
        terms.insert(1 if included_names else 0, f"费用不包含或按实际：{'、'.join(dict.fromkeys(excluded_names))}。")

    valid_until = pricing_date + timedelta(days=config.default_quote_valid_days)
    result = FCLQuoteResult(
        quote_id=quote_id,
        source_type="manual_required" if reasons else "fcl_rate_card",
        normalized_input=normalized,
        cargo_calculation=cargo,
        matched_rate_cards=public_cards,
        fee_items=fee_items,
        totals_by_currency=normalized_totals,
        settlement_currency=settlement_currency,
        converted_total=converted_total,
        exchange_snapshot=exchange_snapshot,
        quote_valid_until=valid_until,
        public_terms=terms,
        company_name=config.company_name,
        company_address=config.company_address,
        company_phone=config.company_phone,
        company_email=config.company_email,
        company_logo=config.company_logo,
        footer=config.footer,
        renderer_version=config.renderer_version,
        manual_review_required=bool(reasons),
        manual_reasons=sorted(dict.fromkeys(reasons)),
        customer_reply=_build_customer_reply(normalized, fee_items, normalized_totals, converted_total, settlement_currency, valid_until, terms, reasons),
    )
    internal_snapshot = {
        "config_version": config_version,
        "renderer_version": config.renderer_version,
        "matched_rate_cards": _json_safe(internal_cards),
        "fee_items": internal_fee_items,
        "totals_by_currency": {key: str(value) for key, value in normalized_totals.items()},
        "exchange_snapshot": exchange_snapshot,
        "public_result": result.model_dump(mode="json"),
    }
    return result, internal_snapshot


def _missing_fields(draft: FCLQuoteDraft, required_fields: list[str], cargo: FCLCargoCalculation) -> list[str]:
    missing: list[str] = []
    checks: dict[str, bool] = {
        "customer_name": not draft.customer_name,
        "contact": not draft.contact,
        "customer_type": not draft.customer_type,
        "pol": not draft.pol,
        "pod": not draft.pod,
        "containers": not draft.containers,
        "cargo_name": not draft.cargo_name,
        "special_attributes": not draft.special_attributes,
        "ready_date": not draft.ready_date,
        "target_etd": not draft.target_etd,
        "importer_exists": not draft.importer_exists,
        "service_scope": not draft.service_scope,
        "service_stages": not draft.service_stages,
        "trade_terms": not draft.trade_terms,
        "export_declaration": not draft.export_declaration,
        "importer_legal_name": not draft.importer_legal_name,
        "bn_rm_status": not draft.bn_rm_status,
        "carm_status": not draft.carm_status,
        "has_broker": not draft.has_broker,
        "tax_included": not draft.tax_included,
        "priority_goal": not draft.priority_goal,
        "address_type": not draft.address_type,
        "tail_lift": not draft.tail_lift,
        "appointment_window": not draft.appointment_window,
        "forklift": not draft.forklift,
        "platform_warehouse": not draft.platform_warehouse,
        "destination_postal_code": not draft.destination_postal_code,
        "destination_address": not draft.destination_address,
        "cargo_value": draft.cargo_value is None or draft.cargo_value <= 0,
        "cargo_value_currency": not draft.cargo_value_currency,
        "hs_code": not draft.hs_code,
        "origin_country": not draft.origin_country,
        "sds_un_info": not draft.sds_un_info,
        "wood_packaging": not draft.wood_packaging,
        "expected_delivery_date": not draft.expected_delivery_date,
        "deadline_strictness": not draft.deadline_strictness,
        "acceptable_transit_days": draft.acceptable_transit_days is None,
        "stackable": draft.stackable is None,
        "declaration_acknowledged": draft.declaration_acknowledged is not True,
    }
    for field in required_fields:
        if field in checks and checks[field]:
            missing.append(field)
    if "cargo" in required_fields and (
        not draft.cargo_name
        or cargo.piece_count is None
        or cargo.piece_count <= 0
        or cargo.total_weight_kg is None
        or cargo.total_weight_kg <= 0
        or cargo.total_volume_cbm is None
        or cargo.total_volume_cbm <= 0
    ):
        missing.append("cargo")
    if draft.service_scope in ("port-to-door", "door-to-door"):
        if not draft.destination_postal_code:
            missing.append("destination_postal_code")
        if not draft.destination_address:
            missing.append("destination_address")
        if not draft.address_type:
            missing.append("address_type")
    if "dangerous_goods" in draft.special_attributes or "battery" in draft.special_attributes:
        if not draft.sds_un_info:
            missing.append("sds_un_info")
    if "wood" in draft.special_attributes:
        if not draft.wood_packaging:
            missing.append("wood_packaging")
    if draft.importer_exists in ("no", "unknown"):
        if not draft.tax_included:
            missing.append("tax_included")
    if draft.cargo_value is not None and not draft.cargo_value_currency:
        missing.append("cargo_value_currency")
    return sorted(set(missing))


def _card_dict(card: Mapping[str, Any] | Any) -> dict[str, Any]:
    if isinstance(card, Mapping):
        return dict(card)
    return {
        key: getattr(card, key, None)
        for key in (
            "id", "pol", "pod", "container_type", "carrier", "service", "service_scope",
            "effective_from", "effective_to", "etd_date", "vessel_voyage", "priority", "source",
            "status", "enabled", "fee_lines",
        )
    }


def _select_rate_card(
    draft: FCLQuoteDraft,
    container_type: str,
    pricing_date: date,
    cards: list[Mapping[str, Any]],
) -> tuple[Mapping[str, Any] | None, str | None]:
    candidates: list[tuple[int, int, str, Mapping[str, Any]]] = []
    for card in cards:
        data = _card_dict(card)
        if data.get("status") != "published" or data.get("enabled") is False:
            continue
        if normalize_port(str(data.get("pol") or "")) != normalize_port(draft.pol):
            continue
        if normalize_port(str(data.get("pod") or "")) != normalize_port(draft.pod):
            continue
        if normalize_container_type(str(data.get("container_type") or "")) != container_type:
            continue
        if not _date_is_effective(data.get("effective_from"), data.get("effective_to"), pricing_date):
            continue
        if data.get("etd_date") is not None and _as_date(data.get("etd_date")) != draft.target_etd:
            continue
        if data.get("vessel_voyage") and data.get("vessel_voyage") != draft.service_preference:
            continue
        if data.get("carrier") and not draft.carrier:
            continue
        if data.get("carrier") and normalize_key(str(data.get("carrier"))) != normalize_key(draft.carrier or ""):
            continue
        if data.get("service") and not draft.service_preference:
            continue
        if data.get("service") and normalize_key(str(data.get("service"))) != normalize_key(draft.service_preference or ""):
            continue
        if data.get("service_scope") and data.get("service_scope") != draft.service_scope:
            continue
        specificity = sum(
            bool(data.get(key))
            for key in ("carrier", "service", "service_scope", "etd_date", "vessel_voyage")
        )
        candidates.append((specificity, int(data.get("priority") or 100), str(data.get("id") or ""), card))

    if not candidates:
        return None, f"no_published_rate_card:{container_type}"
    candidates.sort(key=lambda candidate: (-candidate[0], candidate[1], candidate[2]))
    best_key = candidates[0][:2]
    tied = [candidate for candidate in candidates if candidate[:2] == best_key]
    if len(tied) > 1:
        return None, f"ambiguous_rate_cards:{container_type}:priority_{best_key[1]}"
    return candidates[0][3], None


def _validate_rate_card(data: Mapping[str, Any]) -> FCLRateCardPayload | None:
    try:
        return FCLRateCardPayload.model_validate(
            {
                key: data.get(key)
                for key in (
                    "pol", "pod", "container_type", "carrier", "service", "service_scope",
                    "effective_from", "effective_to", "etd_date", "vessel_voyage", "priority",
                    "source", "enabled", "fee_lines",
                )
            }
        )
    except Exception:
        return None


def _public_rate_card(data: Mapping[str, Any], payload: FCLRateCardPayload) -> dict[str, Any]:
    return {
        "rate_card_id": data.get("id"),
        "pol": normalize_port(payload.pol),
        "pod": normalize_port(payload.pod),
        "container_type": normalize_container_type(payload.container_type),
        "carrier": payload.carrier,
        "service": payload.service,
        "service_scope": payload.service_scope,
        "effective_from": payload.effective_from,
        "effective_to": payload.effective_to,
        "etd_date": payload.etd_date,
        "vessel_voyage": payload.vessel_voyage,
        "priority": payload.priority,
        "source": payload.source,
    }


def _line_quantity(unit: str, container_quantity: int, cargo: FCLCargoCalculation) -> Decimal | None:
    if unit == "container":
        return Decimal(container_quantity)
    if unit == "shipment":
        return Decimal("1")
    if unit == "piece":
        return Decimal(cargo.piece_count) if cargo.piece_count is not None and cargo.piece_count > 0 else None
    if unit == "kg":
        return cargo.total_weight_kg if cargo.total_weight_kg is not None and cargo.total_weight_kg > 0 else None
    if unit == "cbm":
        return cargo.total_volume_cbm if cargo.total_volume_cbm is not None and cargo.total_volume_cbm > 0 else None
    return None


def _resolve_unit_price(line: FCLFeeLine, config: FCLQuoteConfig) -> Decimal | None:
    if line.pricing_status != "auto":
        return None
    if line.sales_unit_price is not None:
        return money(line.sales_unit_price)
    if line.cost_unit_price is None:
        return None
    return money(line.cost_unit_price * (Decimal("1") + config.markup_percent / Decimal("100")) + config.markup_fixed)


def _find_exchange_rate(
    rates: list[FCLExchangeRate],
    from_currency: str,
    to_currency: str,
    pricing_date: date,
) -> FCLExchangeRate | None:
    for rate in rates:
        if rate.from_currency == from_currency and rate.to_currency == to_currency and _date_is_effective(rate.effective_from, rate.effective_to, pricing_date):
            return rate
    return None


def _date_is_effective(start: Any, end: Any, target: date) -> bool:
    start_date = _as_date(start)
    end_date = _as_date(end)
    return (start_date is None or start_date <= target) and (end_date is None or target <= end_date)


def _as_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def _build_customer_reply(
    draft: FCLQuoteDraft,
    fee_items: list[FCLFeeItemPublic],
    totals: dict[str, Decimal],
    converted_total: Decimal | None,
    settlement_currency: str | None,
    valid_until: date,
    terms: list[str],
    manual_reasons: list[str],
) -> str:
    route = f"POL {draft.pol or '待确认'} → POD {draft.pod or '待确认'}"
    containers = "、".join(f"{item.container_type} × {item.quantity}" for item in draft.containers) or "待确认"
    if manual_reasons:
        reason_text = "、".join(_human_reason(reason) for reason in sorted(set(manual_reasons))[:5])
        return "\n".join(["AI 整柜报价需要人工复核。", route, f"柜量：{containers}", "当前未生成可直接发送客户的确定金额。", reason_text]).strip()
    lines = ["AI 整柜报价如下：", route, f"柜量：{containers}"]
    visible = [item for item in fee_items if item.display_mode in ("both", "quoteOnly", "merged")]
    if visible:
        lines.append("费用明细：")
        for item in visible:
            amount = f"{item.currency} {item.amount:.2f}" if item.amount is not None else "按实际/人工确认"
            lines.append(f"- {item.item_name}：{amount}")
    lines.append("报价合计：" + "；".join(f"{currency} {amount:.2f}" for currency, amount in totals.items()))
    if converted_total is not None and settlement_currency:
        lines.append(f"折算合计：{settlement_currency} {converted_total:.2f}")
    lines.append(f"报价有效期至：{valid_until.isoformat()}")
    if terms:
        lines.append("条款：")
        lines.extend(f"- {term}" for term in terms)
    return "\n".join(lines)


def _human_reason(reason: str) -> str:
    if reason.startswith("missing:"):
        return f"缺少 {reason.split(':', 1)[1]}"
    if reason.endswith("_conflict"):
        return "货物声明值与分项重算值不一致"
    if reason.startswith("no_published_rate_card"):
        return "未匹配到有效已发布费率"
    if reason.startswith("ambiguous_rate_cards"):
        return "费率存在同优先级冲突"
    if reason.startswith("exchange_rate_"):
        return "汇率快照缺失或已过期"
    if reason == "hard_deadline_manual_review":
        return "硬性时限需人工确认可行性"
    if reason == "importer_condition_manual_review":
        return "无确定加拿大进口商，需包税/人工审核"
    if reason == "wood_packaging_pending":
        return "木质包装状态待确认"
    if reason == "export_declaration_pending":
        return "中国出口报关能力待确认"
    if reason == "non_stackable_manual_review":
        return "货物不可叠放，需人工确认"
    return reason


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value
