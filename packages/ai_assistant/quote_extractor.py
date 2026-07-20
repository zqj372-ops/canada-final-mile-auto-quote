from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
import re
import unicodedata
from typing import Any, Callable, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from packages.ai_assistant.model_client import AIMessage, BaseAIClient
from packages.ai_assistant.prompts import (
    ADDRESS_EXTRACTION_SYSTEM_PROMPT,
    CARGO_EXTRACTION_SYSTEM_PROMPT,
    FIELD_EXTRACTION_SYSTEM_PROMPT,
)


class ExtractedCargoItem(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    quantity: int = Field(default=1, ge=1)
    length_cm: Decimal | None = Field(default=None, ge=0)
    width_cm: Decimal | None = Field(default=None, ge=0)
    height_cm: Decimal | None = Field(default=None, ge=0)
    weight_kg: Decimal | None = Field(default=None, ge=0)
    cbm: Decimal | None = Field(default=None, ge=0)
    total_weight_kg: Decimal | None = Field(default=None, ge=0)
    total_cbm: Decimal | None = Field(default=None, ge=0)
    source_span: str | None = None


class AIExtractedQuoteDraft(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    province: str | None = None
    cbm: Decimal | None = Field(default=None, ge=0)
    weight_kg: Decimal | None = Field(default=None, ge=0)
    piece_count: int | None = Field(default=None, ge=1)
    packaging_type: str | None = None
    longest_side_cm: Decimal | None = Field(default=None, ge=0)
    explicit_pallet_count: int | None = Field(default=None, ge=1)
    is_stackable: bool | None = None
    address_type: str | None = None
    requires_liftgate: bool = False
    requires_pallet_jack: bool = False
    requires_appointment: bool = False
    detention_minutes: int = Field(default=0, ge=0)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)
    extraction_notes: str | None = None
    cargo_items: list[ExtractedCargoItem] = Field(default_factory=list)
    cargo_agent: dict[str, Any] | None = None
    address_agent: dict[str, Any] | None = None
    validation_notes: list[str] = Field(default_factory=list)

    @field_validator("packaging_type")
    @classmethod
    def normalize_packaging_type(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value

    @field_validator("address_type")
    @classmethod
    def normalize_address_type(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value


class CargoAgentExtraction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    cbm: Decimal | None = Field(default=None, ge=0)
    weight_kg: Decimal | None = Field(default=None, ge=0)
    piece_count: int | None = Field(default=None, ge=1)
    packaging_type: str | None = None
    longest_side_cm: Decimal | None = Field(default=None, ge=0)
    explicit_pallet_count: int | None = Field(default=None, ge=1)
    is_stackable: bool | None = None
    cargo_items: list[ExtractedCargoItem] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)
    extraction_notes: str | None = None


class AddressAgentExtraction(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None
    province: str | None = None
    country: str | None = None
    address_type: str | None = None
    requires_liftgate: bool = False
    requires_pallet_jack: bool = False
    requires_appointment: bool = False
    detention_minutes: int = Field(default=0, ge=0)
    missing_fields: list[str] = Field(default_factory=list)
    confidence: int = Field(default=0, ge=0, le=100)
    extraction_notes: str | None = None


class QuoteExtractionError(Exception):
    pass


ExtractionModel = TypeVar("ExtractionModel", bound=BaseModel)


REQUIRED_FIELDS = {
    "postal_code",
    "cbm",
    "weight_kg",
    "piece_count",
    "packaging_type",
    "address_type",
}
ALLOWED_PACKAGING_TYPES = {"carton", "wooden_crate", "pallet", "woven_bag", "flexible_packaging", "unknown"}
ALLOWED_ADDRESS_TYPES = {"commercial", "residential", "private", "rural_residential"}
POSTAL_CODE_PATTERN = re.compile(r"[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d")
SUSPICIOUS_MODEL_PIECE_COUNT = 1000
SUSPICIOUS_PIECES_PER_CBM = Decimal("500")
NUMBER_TOKEN_PATTERN = r"(?:\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:[.,]\d+)?)"
PIECE_UNIT_PATTERN = (
    r"(?:pcs?|pieces?|units?|ctns?|cartons?|boxes|pkgs?|packages?|cases?|bags?|sacks?|"
    r"rolls?|drums?|crates?|skids?|skds?|bundles?|sets?|pallets?|plts?|件|箱|包|袋|卷|桶|架|捆|套|台|托盘|托)"
)
DIMENSION_UNIT_PATTERN = (
    r"(?:millimet(?:er|re)s?|mms?|centimet(?:er|re)s?|cms?|met(?:er|re)s?|mm|cm|m|"
    r"毫米|厘米|米|inches|inch|in|\"|feet|foot|ft|英尺|英寸)"
)
WEIGHT_UNIT_PATTERN = (
    r"(?:metric\s*(?:tons?|tonnes?)|tonnes?|kilograms?|kgs?|kg|公斤|千克|"
    r"pounds?|lbs?|lb|磅|grams?|g|克|m\.?t\.?|t)"
)
VOLUME_UNIT_PATTERN = (
    r"(?:c\.?b\.?m\.?|m(?:\^?3|³)|cubic\s*met(?:er|re)s?|cu\.?\s*ft|cuft|cft|"
    r"ft(?:\^?3|³)|cubic\s*(?:feet|foot)|cu\.?\s*in|cuin|cin|in(?:\^?3|³)|"
    r"cubic\s*inches?|立方米?|方)"
)
PIECE_COUNT_LABEL_PATTERN = (
    rf"(?:qty|quantity|(?:no\.?|number|#)\s*of\s*{PIECE_UNIT_PATTERN}|"
    r"pkg\s*count|package\s*count|piece_count|数量|箱数|件数|总件数|总箱数)"
)
TOTAL_WEIGHT_LABEL_PATTERN = (
    r"(?:total\s*(?:gross\s*)?(?:weight|wt)|ttl\s*(?:weight|wt)|gross\s*(?:weight|wt)|"
    r"g(?:\.|/)?\s*w(?:t)?\.?|t\.?\s*w\.?|总重量|总重|重量合计|总毛重)"
)
VOLUME_LABEL_PATTERN = (
    r"(?:total\s*(?:volume|vol\.?|cube|cbm)|ttl\s*(?:volume|vol\.?|cube|cbm)|"
    r"volume|vol\.?|meas(?:urement)?\.?|cube|c\.?b\.?m\.?|cuft|cft|"
    r"总体积|总方数|方数|体积)"
)
PROVINCE_ALIASES = {
    "alberta": "AB",
    "ab": "AB",
    "british columbia": "BC",
    "b.c.": "BC",
    "bc": "BC",
    "manitoba": "MB",
    "mb": "MB",
    "new brunswick": "NB",
    "nb": "NB",
    "newfoundland and labrador": "NL",
    "newfoundland": "NL",
    "labrador": "NL",
    "nl": "NL",
    "nova scotia": "NS",
    "ns": "NS",
    "northwest territories": "NT",
    "nt": "NT",
    "nunavut": "NU",
    "nu": "NU",
    "ontario": "ON",
    "on": "ON",
    "prince edward island": "PE",
    "pei": "PE",
    "pe": "PE",
    "quebec": "QC",
    "québec": "QC",
    "qc": "QC",
    "saskatchewan": "SK",
    "sk": "SK",
    "yukon": "YT",
    "yt": "YT",
}


def extract_quote_draft(customer_message: str, client: BaseAIClient) -> AIExtractedQuoteDraft:
    draft = _complete_validated_extraction(
        customer_message,
        client,
        system_prompt=FIELD_EXTRACTION_SYSTEM_PROMPT,
        sanitizer=_sanitize_extraction_data,
        model_type=AIExtractedQuoteDraft,
    )
    draft = apply_deterministic_extraction(draft, customer_message)
    draft.missing_fields = sorted(missing_required_fields(draft))
    return draft


def extract_quote_draft_with_agents(customer_message: str, client: BaseAIClient) -> AIExtractedQuoteDraft:
    """Extract quote fields with separate cargo and address agents, then validate deterministically."""

    errors: list[str] = []
    cargo: CargoAgentExtraction | None = None
    address: AddressAgentExtraction | None = None

    with ThreadPoolExecutor(max_workers=2) as executor:
        cargo_future = executor.submit(_extract_cargo_with_agent, customer_message, client)
        address_future = executor.submit(_extract_address_with_agent, customer_message, client)
        for label, future in (("cargo", cargo_future), ("address", address_future)):
            try:
                if label == "cargo":
                    cargo = future.result()
                else:
                    address = future.result()
            except QuoteExtractionError as exc:
                errors.append(f"{label}_agent_failed:{exc}")

    if cargo is None and address is None:
        raise QuoteExtractionError("; ".join(errors) or "Both extraction agents failed.")

    draft = _draft_from_agent_outputs(cargo, address)
    fallback = apply_deterministic_extraction(AIExtractedQuoteDraft(confidence=0), customer_message)
    draft = _merge_agent_draft_with_fallback(draft, fallback)
    draft = _reconcile_with_explicit_facts(draft, fallback, customer_message)
    draft = _validate_cargo_items_and_totals(draft)
    if errors:
        draft.validation_notes.extend(errors)
    draft.missing_fields = sorted(missing_required_fields(draft))
    return draft


def _extract_cargo_with_agent(customer_message: str, client: BaseAIClient) -> CargoAgentExtraction:
    return _complete_validated_extraction(
        customer_message,
        client,
        system_prompt=CARGO_EXTRACTION_SYSTEM_PROMPT,
        sanitizer=_sanitize_cargo_agent_data,
        model_type=CargoAgentExtraction,
    )


def _extract_address_with_agent(customer_message: str, client: BaseAIClient) -> AddressAgentExtraction:
    return _complete_validated_extraction(
        customer_message,
        client,
        system_prompt=ADDRESS_EXTRACTION_SYSTEM_PROMPT,
        sanitizer=_sanitize_address_agent_data,
        model_type=AddressAgentExtraction,
    )


def _complete_validated_extraction(
    customer_message: str,
    client: BaseAIClient,
    *,
    system_prompt: str,
    sanitizer: Callable[[dict[str, Any]], dict[str, Any]],
    model_type: type[ExtractionModel],
) -> ExtractionModel:
    messages = [
        AIMessage(role="system", content=system_prompt),
        AIMessage(role="user", content=customer_message),
    ]
    response = client.complete(messages)
    if response.error:
        raise QuoteExtractionError(response.error)

    try:
        return model_type.model_validate(sanitizer(_parse_json_object(response.content)))
    except (QuoteExtractionError, ValidationError) as first_error:
        repair = client.complete(
            [
                *messages,
                AIMessage(role="assistant", content=response.content[:6000]),
                AIMessage(
                    role="user",
                    content=(
                        "上次输出未通过 JSON/schema 校验："
                        f"{_compact_validation_error(first_error)}。"
                        "请重新核对原始消息并输出完整 JSON；只输出 JSON。"
                    ),
                ),
            ]
        )
        if repair.error:
            raise QuoteExtractionError(repair.error) from first_error
        try:
            return model_type.model_validate(sanitizer(_parse_json_object(repair.content)))
        except (QuoteExtractionError, ValidationError) as repair_error:
            raise QuoteExtractionError("AI extraction failed schema validation after one repair retry.") from repair_error


def _compact_validation_error(error: Exception) -> str:
    return " ".join(str(error).split())[:1000]


def _draft_from_agent_outputs(
    cargo: CargoAgentExtraction | None,
    address: AddressAgentExtraction | None,
) -> AIExtractedQuoteDraft:
    confidences = [item.confidence for item in (cargo, address) if item and item.confidence]
    notes = [
        item.extraction_notes
        for item in (cargo, address)
        if item and item.extraction_notes
    ]
    return AIExtractedQuoteDraft(
        address_line=address.address_line if address else None,
        postal_code=address.postal_code if address else None,
        city=address.city if address else None,
        province=address.province if address else None,
        cbm=cargo.cbm if cargo else None,
        weight_kg=cargo.weight_kg if cargo else None,
        piece_count=cargo.piece_count if cargo else None,
        packaging_type=cargo.packaging_type if cargo else None,
        longest_side_cm=cargo.longest_side_cm if cargo else None,
        explicit_pallet_count=cargo.explicit_pallet_count if cargo else None,
        is_stackable=cargo.is_stackable if cargo else None,
        address_type=address.address_type if address else None,
        requires_liftgate=address.requires_liftgate if address else False,
        requires_pallet_jack=address.requires_pallet_jack if address else False,
        requires_appointment=address.requires_appointment if address else False,
        detention_minutes=address.detention_minutes if address else 0,
        missing_fields=sorted({*(cargo.missing_fields if cargo else []), *(address.missing_fields if address else [])}),
        confidence=int(sum(confidences) / len(confidences)) if confidences else 0,
        extraction_notes=" | ".join(notes) if notes else None,
        cargo_items=cargo.cargo_items if cargo else [],
        cargo_agent=cargo.model_dump(mode="json") if cargo else None,
        address_agent=address.model_dump(mode="json") if address else None,
        validation_notes=["dual_agent_extraction"],
    )


def _merge_agent_draft_with_fallback(
    draft: AIExtractedQuoteDraft,
    fallback: AIExtractedQuoteDraft,
) -> AIExtractedQuoteDraft:
    for field in (
        "address_line",
        "postal_code",
        "city",
        "province",
        "cbm",
        "weight_kg",
        "piece_count",
        "packaging_type",
        "longest_side_cm",
        "explicit_pallet_count",
        "is_stackable",
        "address_type",
    ):
        if getattr(draft, field) in (None, ""):
            setattr(draft, field, getattr(fallback, field))

    draft.requires_liftgate = draft.requires_liftgate or fallback.requires_liftgate
    draft.requires_pallet_jack = draft.requires_pallet_jack or fallback.requires_pallet_jack
    draft.requires_appointment = draft.requires_appointment or fallback.requires_appointment
    draft.detention_minutes = draft.detention_minutes or fallback.detention_minutes

    if not draft.cargo_items and fallback.cargo_items:
        draft.cargo_items = fallback.cargo_items

    if fallback.confidence and draft.confidence < 75:
        draft.confidence = max(draft.confidence, min(85, fallback.confidence))

    notes = [note for note in (draft.extraction_notes, fallback.extraction_notes) if note]
    if notes:
        draft.extraction_notes = " | ".join(dict.fromkeys(notes))
    for note in fallback.validation_notes:
        if note not in draft.validation_notes:
            draft.validation_notes.append(note)
    return draft


def _reconcile_with_explicit_facts(
    draft: AIExtractedQuoteDraft,
    fallback: AIExtractedQuoteDraft,
    customer_message: str,
) -> AIExtractedQuoteDraft:
    """Let explicit source facts and UI-confirmed fields overrule model guesses."""

    corrections: list[str] = []
    has_correction_language = bool(re.search(r"(?:更正|改为|修改为|不是.{0,20}是|以.+为准)", customer_message))
    explicit_piece_count = None if has_correction_language else _find_authoritative_piece_count(customer_message)
    explicit_weight = None if has_correction_language else _find_authoritative_weight(customer_message)

    if explicit_piece_count is not None:
        if draft.piece_count != explicit_piece_count:
            corrections.append("piece_count")
        draft.piece_count = explicit_piece_count
        draft.cargo_items = _reconcile_cargo_item_quantities(
            draft.cargo_items,
            fallback.cargo_items,
            piece_count=explicit_piece_count,
            total_weight_kg=explicit_weight or draft.weight_kg,
            total_cbm=draft.cbm,
        )

    if explicit_weight is not None:
        normalized_weight = _quantize(explicit_weight, "0.1")
        if draft.weight_kg != normalized_weight:
            corrections.append("weight_kg")
        draft.weight_kg = normalized_weight

    before_confirmed = {
        field: getattr(draft, field)
        for field in (
            "address_line",
            "postal_code",
            "city",
            "province",
            "packaging_type",
            "address_type",
            "requires_liftgate",
            "requires_pallet_jack",
            "requires_appointment",
            "detention_minutes",
            "explicit_pallet_count",
            "is_stackable",
        )
    }
    _apply_confirmed_fields(draft, _parse_confirmed_fields(customer_message))
    if any(getattr(draft, field) != value for field, value in before_confirmed.items()):
        corrections.append("confirmed_fields")

    if corrections:
        draft.validation_notes.append(f"explicit_source_override:{','.join(dict.fromkeys(corrections))}")
    return draft


def _reconcile_cargo_item_quantities(
    cargo_items: list[ExtractedCargoItem],
    fallback_items: list[ExtractedCargoItem],
    *,
    piece_count: int,
    total_weight_kg: Decimal | None,
    total_cbm: Decimal | None,
) -> list[ExtractedCargoItem]:
    if sum(item.quantity for item in cargo_items) == piece_count:
        return cargo_items
    if fallback_items and sum(item.quantity for item in fallback_items) == piece_count:
        return fallback_items
    if len(cargo_items) != 1:
        return []

    item = cargo_items[0]
    updates: dict[str, Any] = {
        "quantity": piece_count,
        "total_weight_kg": total_weight_kg,
        "total_cbm": total_cbm,
    }
    if total_weight_kg is not None:
        updates["weight_kg"] = _quantize(total_weight_kg / Decimal(piece_count), "0.01")
    return [item.model_copy(update=updates)]


def _validate_cargo_items_and_totals(draft: AIExtractedQuoteDraft) -> AIExtractedQuoteDraft:
    if not draft.cargo_items:
        return draft

    normalized_items: list[ExtractedCargoItem] = []
    total_quantity = 0
    computed_cbm = Decimal("0")
    computed_weight = Decimal("0")
    longest_side_cm: Decimal | None = None
    for item in draft.cargo_items:
        normalized = _normalize_cargo_item(item)
        normalized_items.append(normalized)
        total_quantity += normalized.quantity
        if normalized.cbm is not None:
            computed_cbm += normalized.cbm * Decimal(normalized.quantity)
        if normalized.weight_kg is not None:
            computed_weight += normalized.weight_kg * Decimal(normalized.quantity)
        dimensions = [normalized.length_cm, normalized.width_cm, normalized.height_cm]
        known_dimensions = [value for value in dimensions if value is not None]
        if known_dimensions:
            item_longest = max(known_dimensions)
            longest_side_cm = item_longest if longest_side_cm is None else max(longest_side_cm, item_longest)

    draft.cargo_items = normalized_items
    if draft.piece_count is None or total_quantity > draft.piece_count:
        draft.piece_count = total_quantity
    if draft.cbm is None and computed_cbm > 0:
        draft.cbm = _quantize(computed_cbm, "0.001")
    if draft.weight_kg is None and computed_weight > 0:
        draft.weight_kg = _quantize(computed_weight, "0.1")
    if draft.longest_side_cm is None and longest_side_cm is not None:
        draft.longest_side_cm = _quantize(longest_side_cm, "0.1")

    _split_aggregate_weight_for_single_cargo_item(draft)
    return draft


def _normalize_cargo_item(item: ExtractedCargoItem) -> ExtractedCargoItem:
    cbm = item.cbm
    if cbm is None and item.length_cm is not None and item.width_cm is not None and item.height_cm is not None:
        cbm = _quantize(item.length_cm * item.width_cm * item.height_cm / Decimal("1000000"), "0.001")
    if cbm is None and item.total_cbm is not None and item.quantity:
        cbm = _quantize(item.total_cbm / Decimal(item.quantity), "0.000001")

    weight_kg = item.weight_kg
    if weight_kg is None and item.total_weight_kg is not None and item.quantity:
        weight_kg = item.total_weight_kg / Decimal(item.quantity)

    return item.model_copy(
        update={
            "length_cm": _quantize(item.length_cm, "0.1") if item.length_cm is not None else None,
            "width_cm": _quantize(item.width_cm, "0.1") if item.width_cm is not None else None,
            "height_cm": _quantize(item.height_cm, "0.1") if item.height_cm is not None else None,
            "weight_kg": _quantize(weight_kg, "0.01") if weight_kg is not None else None,
            "cbm": cbm,
        }
    )


def _split_aggregate_weight_for_single_cargo_item(draft: AIExtractedQuoteDraft) -> None:
    if len(draft.cargo_items) != 1 or draft.weight_kg is None:
        return
    item = draft.cargo_items[0]
    quantity = draft.piece_count or item.quantity
    if quantity == 1 and item.weight_kg is None:
        draft.cargo_items[0] = item.model_copy(
            update={
                "weight_kg": _quantize(draft.weight_kg, "0.01"),
                "total_weight_kg": draft.weight_kg,
                "total_cbm": draft.cbm,
            }
        )
        draft.validation_notes.append("applied_total_weight_to_single_cargo_item")
        return
    if quantity <= 1:
        return

    expected_total = item.weight_kg * Decimal(quantity) if item.weight_kg is not None else None
    tolerance = max(Decimal("1"), draft.weight_kg * Decimal("0.05"))
    should_split = expected_total is None or abs(expected_total - draft.weight_kg) > tolerance
    if not should_split:
        return

    per_piece_weight = draft.weight_kg / Decimal(quantity)
    draft.cargo_items[0] = item.model_copy(
        update={
            "quantity": quantity,
            "weight_kg": _quantize(per_piece_weight, "0.01"),
            "total_weight_kg": draft.weight_kg,
            "total_cbm": draft.cbm,
        }
    )
    draft.validation_notes.append("split_total_weight_across_single_cargo_line")


def apply_deterministic_extraction(draft: AIExtractedQuoteDraft, customer_message: str) -> AIExtractedQuoteDraft:
    confirmed = _parse_confirmed_fields(customer_message)
    _clear_placeholder_fields(draft)
    parsed = _parse_measurements(customer_message)
    if parsed["piece_count"]:
        draft.piece_count = int(parsed["piece_count"])
    if parsed["cbm"] is not None:
        draft.cbm = parsed["cbm"]
    if parsed["weight_kg"] is not None:
        draft.weight_kg = parsed["weight_kg"]
    if parsed["longest_side_cm"] is not None:
        draft.longest_side_cm = parsed["longest_side_cm"]
    if parsed["cargo_items"]:
        draft.cargo_items = parsed["cargo_items"]

    postal_code = _find_postal_code(customer_message)
    if postal_code and not draft.postal_code:
        draft.postal_code = postal_code
    province = _find_province(customer_message)
    if province and not draft.province:
        draft.province = province
    address = _parse_address_fields(customer_message)
    if address["address_line"] and not draft.address_line:
        draft.address_line = address["address_line"]
    if address["city"] and not draft.city:
        draft.city = address["city"]
    if address["province"] and not draft.province:
        draft.province = address["province"]
    if address["postal_code"] and not draft.postal_code:
        draft.postal_code = address["postal_code"]
    packaging = _infer_packaging_type(customer_message)
    if packaging and not draft.packaging_type:
        draft.packaging_type = packaging
    explicit_pallet_count = _find_explicit_pallet_count(customer_message)
    if explicit_pallet_count is not None:
        draft.explicit_pallet_count = explicit_pallet_count
    _apply_confirmed_fields(draft, confirmed)

    notes = list(filter(None, [draft.extraction_notes]))
    if parsed["notes"]:
        notes.append(parsed["notes"])
    suspicious_note = _clear_suspicious_model_piece_count(draft, customer_message)
    if suspicious_note:
        notes.append(suspicious_note)
    if notes:
        draft.extraction_notes = " | ".join(notes)
    if parsed["piece_count"] and draft.confidence < 75:
        draft.confidence = max(draft.confidence, 75)
    _clear_placeholder_fields(draft)
    return _validate_cargo_items_and_totals(draft)


def _clear_suspicious_model_piece_count(
    draft: AIExtractedQuoteDraft,
    customer_message: str,
) -> str | None:
    if draft.piece_count is None or draft.piece_count < SUSPICIOUS_MODEL_PIECE_COUNT:
        return None
    if _find_explicit_piece_count(customer_message) is not None:
        return None

    cbm = draft.cbm or Decimal("0")
    pieces_per_cbm = Decimal(draft.piece_count) / cbm if cbm > 0 else Decimal("0")
    is_long_piece = bool(draft.longest_side_cm is not None and draft.longest_side_cm >= Decimal("240"))
    if not is_long_piece and pieces_per_cbm <= SUSPICIOUS_PIECES_PER_CBM:
        return None

    original_piece_count = draft.piece_count
    draft.piece_count = None
    return (
        f"Ignored suspicious model piece_count={original_piece_count}; "
        "original text did not explicitly confirm that many shipping pieces."
    )


def missing_required_fields(draft: AIExtractedQuoteDraft) -> set[str]:
    missing: set[str] = set()
    for field in REQUIRED_FIELDS:
        value = getattr(draft, field)
        if value is None or value == "":
            missing.add(field)
    if draft.packaging_type not in ALLOWED_PACKAGING_TYPES:
        missing.add("packaging_type")
    if draft.address_type not in ALLOWED_ADDRESS_TYPES:
        missing.add("address_type")
    return missing


def _clear_placeholder_fields(draft: AIExtractedQuoteDraft) -> None:
    if _is_placeholder_value(draft.address_line):
        draft.address_line = None
    if _is_placeholder_value(draft.city):
        draft.city = None
    if _is_placeholder_value(draft.province):
        draft.province = None


def _is_placeholder_value(value: str | None) -> bool:
    if value is None:
        return False
    normalized = value.strip().lower()
    return normalized in {"", "-", "--", "---", "n/a", "na", "null", "none", "unknown", "待确认", "未知"}


def build_follow_up_question(missing_fields: list[str]) -> str:
    if not missing_fields:
        return ""
    labels = {
        "postal_code": "加拿大邮编",
        "cbm": "总体积 CBM",
        "weight_kg": "总重量 kg",
        "piece_count": "件数",
        "packaging_type": "包装类型",
        "address_type": "地址类型（商业/住宅/私人/偏远住宅）",
    }
    readable = "、".join(labels.get(field, field) for field in missing_fields)
    return f"这票还缺少 {readable}。麻烦补充后我再帮你确认报价。"


def _parse_json_object(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    stripped = re.sub(r"<think>.*?</think>", "", stripped, flags=re.IGNORECASE | re.DOTALL).strip()
    if not stripped.startswith("{"):
        stripped = _extract_first_json_object(stripped)
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise QuoteExtractionError("AI extraction did not return valid JSON.") from exc
    if not isinstance(data, dict):
        raise QuoteExtractionError("AI extraction JSON must be an object.")
    return data


def _sanitize_extraction_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    for field in ["requires_liftgate", "requires_pallet_jack", "requires_appointment"]:
        normalized[field] = _coerce_bool(normalized.get(field), default=False)
    normalized["detention_minutes"] = _coerce_int(normalized.get("detention_minutes"), default=0)
    normalized["piece_count"] = _coerce_optional_int(normalized.get("piece_count"))
    normalized["explicit_pallet_count"] = _coerce_optional_int(normalized.get("explicit_pallet_count"))
    normalized["confidence"] = _coerce_confidence(normalized.get("confidence"))
    missing_fields = normalized.get("missing_fields")
    if missing_fields is None:
        normalized["missing_fields"] = []
    elif isinstance(missing_fields, str):
        normalized["missing_fields"] = [missing_fields]
    elif not isinstance(missing_fields, list):
        normalized["missing_fields"] = []
    normalized["cargo_items"] = _sanitize_cargo_items(normalized.get("cargo_items"))
    validation_notes = normalized.get("validation_notes")
    if validation_notes is None:
        normalized["validation_notes"] = []
    elif isinstance(validation_notes, str):
        normalized["validation_notes"] = [validation_notes]
    elif not isinstance(validation_notes, list):
        normalized["validation_notes"] = []
    return normalized


def _sanitize_cargo_agent_data(data: dict[str, Any]) -> dict[str, Any]:
    normalized = {
        "cbm": _coerce_optional_decimal(data.get("cbm")),
        "weight_kg": _coerce_optional_decimal(data.get("weight_kg")),
        "piece_count": _coerce_optional_int(data.get("piece_count")),
        "packaging_type": _none_if_placeholder(data.get("packaging_type")),
        "longest_side_cm": _coerce_optional_decimal(data.get("longest_side_cm")),
        "explicit_pallet_count": _coerce_optional_int(data.get("explicit_pallet_count")),
        "is_stackable": _coerce_optional_bool(data.get("is_stackable")),
        "cargo_items": _sanitize_cargo_items(data.get("cargo_items")),
        "missing_fields": _coerce_string_list(data.get("missing_fields")),
        "confidence": _coerce_confidence(data.get("confidence")),
        "extraction_notes": _none_if_placeholder(data.get("extraction_notes")),
    }
    return normalized


def _sanitize_address_agent_data(data: dict[str, Any]) -> dict[str, Any]:
    postal_code = data.get("postal_code")
    province = data.get("province")
    normalized = {
        "address_line": _none_if_placeholder(data.get("address_line")),
        "postal_code": _find_postal_code(str(postal_code)) if postal_code else None,
        "city": _none_if_placeholder(data.get("city")),
        "province": _find_province(str(province)) or (str(province).upper() if province and not _is_placeholder_value(str(province)) else None),
        "country": _none_if_placeholder(data.get("country")),
        "address_type": _none_if_placeholder(data.get("address_type")),
        "requires_liftgate": _coerce_bool(data.get("requires_liftgate"), default=False),
        "requires_pallet_jack": _coerce_bool(data.get("requires_pallet_jack"), default=False),
        "requires_appointment": _coerce_bool(data.get("requires_appointment"), default=False),
        "detention_minutes": _coerce_int(data.get("detention_minutes"), default=0),
        "missing_fields": _coerce_string_list(data.get("missing_fields")),
        "confidence": _coerce_confidence(data.get("confidence")),
        "extraction_notes": _none_if_placeholder(data.get("extraction_notes")),
    }
    return normalized


def _sanitize_cargo_items(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    items: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        quantity = _coerce_optional_int(item.get("quantity")) or 1
        items.append(
            {
                "quantity": quantity,
                "length_cm": _coerce_optional_decimal(item.get("length_cm")),
                "width_cm": _coerce_optional_decimal(item.get("width_cm")),
                "height_cm": _coerce_optional_decimal(item.get("height_cm")),
                "weight_kg": _coerce_optional_decimal(item.get("weight_kg")),
                "cbm": _coerce_optional_decimal(item.get("cbm")),
                "total_weight_kg": _coerce_optional_decimal(item.get("total_weight_kg")),
                "total_cbm": _coerce_optional_decimal(item.get("total_cbm")),
                "source_span": _none_if_placeholder(item.get("source_span")),
            }
        )
    return items


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None and str(item).strip()]


def _none_if_placeholder(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str) and _is_placeholder_value(value):
        return None
    return value


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "yes", "y", "1", "需要", "是"}:
            return True
        if lowered in {"false", "no", "n", "0", "不需要", "否", "none", "null", ""}:
            return False
    return default


def _coerce_optional_bool(value: Any) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and _is_placeholder_value(value):
        return None
    return _coerce_bool(value, default=False)


def _coerce_int(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(Decimal(str(value)))
    except Exception:
        return default


def _coerce_optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(Decimal(str(value)))
    except Exception:
        return None
    return number if number >= 1 else None


def _coerce_optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, str) and _is_placeholder_value(value):
        return None
    try:
        number = Decimal(str(value))
    except Exception:
        return None
    return number if number >= 0 else None


def _coerce_confidence(value: Any) -> int:
    if value is None or value == "":
        return 0
    if isinstance(value, str):
        lowered = value.strip().lower()
        mapping = {"high": 85, "medium": 60, "low": 35, "高": 85, "中": 60, "低": 35}
        if lowered in mapping:
            return mapping[lowered]
        value = lowered.rstrip("%")
    try:
        number = int(Decimal(str(value)))
    except Exception:
        return 0
    return max(0, min(100, number))


def _extract_first_json_object(content: str) -> str:
    start = content.find("{")
    if start < 0:
        return content

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(content)):
        char = content[index]
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return content[start : index + 1]
    return content[start:]


def _parse_measurements(customer_message: str) -> dict[str, Any]:
    total_cbm = Decimal("0")
    total_weight_kg = Decimal("0")
    piece_count = 0
    longest_side_cm: Decimal | None = None
    cargo_items: list[ExtractedCargoItem] = []
    parsed_lines = 0
    allow_numeric_table = _has_dimension_weight_table(customer_message)

    for line in customer_message.splitlines():
        items = _parse_measurement_line(line, allow_numeric_table=allow_numeric_table)
        if not items:
            continue
        parsed_lines += 1
        for item in items:
            quantity = item["quantity"]
            length_cm = item["length_cm"]
            width_cm = item["width_cm"]
            height_cm = item["height_cm"]
            weight_kg = item["weight_kg"]
            item_cbm = length_cm * width_cm * height_cm / Decimal("1000000")
            total_cbm += item_cbm * quantity
            total_weight_kg += weight_kg * quantity
            piece_count += int(quantity)
            line_longest = max(length_cm, width_cm, height_cm)
            longest_side_cm = line_longest if longest_side_cm is None else max(longest_side_cm, line_longest)
            cargo_items.append(
                ExtractedCargoItem(
                    quantity=int(quantity),
                    length_cm=_quantize(length_cm, "0.1"),
                    width_cm=_quantize(width_cm, "0.1"),
                    height_cm=_quantize(height_cm, "0.1"),
                    weight_kg=_quantize(weight_kg, "0.01") if weight_kg > 0 else None,
                    cbm=_quantize(item_cbm, "0.001"),
                    source_span=line.strip()[:240] or None,
                )
            )

    explicit_cbm = _find_explicit_cbm(customer_message)
    explicit_piece_count = _find_explicit_piece_count(customer_message)
    explicit_weight = _find_explicit_weight(customer_message)
    per_piece_weight = _find_per_piece_weight(customer_message)
    if explicit_weight is None and explicit_piece_count is not None:
        if per_piece_weight is not None and len(cargo_items) <= 1:
            explicit_weight = per_piece_weight * Decimal(explicit_piece_count)
        elif explicit_cbm is not None:
            explicit_weight = _find_any_weight(customer_message)

    if explicit_cbm is not None:
        total_cbm = explicit_cbm
    if explicit_weight is not None:
        total_weight_kg = explicit_weight
    if explicit_piece_count is not None and explicit_piece_count >= piece_count:
        parsed_piece_count = piece_count
        cargo_items = _align_single_parsed_cargo_item_with_explicit_totals(
            cargo_items,
            explicit_piece_count=explicit_piece_count,
            explicit_weight=explicit_weight,
            explicit_cbm=explicit_cbm,
        )
        piece_count = explicit_piece_count
        if (
            explicit_cbm is None
            and parsed_piece_count > 0
            and explicit_piece_count > parsed_piece_count
            and len(cargo_items) == 1
        ):
            total_cbm = total_cbm / Decimal(parsed_piece_count) * Decimal(explicit_piece_count)
    if not cargo_items and piece_count > 0 and (total_cbm > 0 or total_weight_kg > 0):
        cargo_items = [
            _build_aggregate_cargo_item(
                customer_message,
                piece_count=piece_count,
                total_cbm=total_cbm if total_cbm > 0 else None,
                total_weight_kg=total_weight_kg if total_weight_kg > 0 else None,
            )
        ]

    return {
        "piece_count": piece_count,
        "cbm": _quantize(total_cbm, "0.001") if total_cbm > 0 else None,
        "weight_kg": _quantize(total_weight_kg, "0.1") if total_weight_kg > 0 else None,
        "longest_side_cm": _quantize(longest_side_cm, "0.1") if longest_side_cm is not None else None,
        "cargo_items": cargo_items,
        "notes": (
            f"Deterministic parser normalized {piece_count} piece(s) from {parsed_lines} cargo line(s)."
            if piece_count
            else None
        ),
    }


def _build_aggregate_cargo_item(
    customer_message: str,
    *,
    piece_count: int,
    total_cbm: Decimal | None,
    total_weight_kg: Decimal | None,
) -> ExtractedCargoItem:
    quantity = Decimal(piece_count)
    return ExtractedCargoItem(
        quantity=piece_count,
        weight_kg=(
            _quantize(total_weight_kg / quantity, "0.01")
            if total_weight_kg is not None
            else None
        ),
        cbm=(
            _quantize(total_cbm / quantity, "0.000001")
            if total_cbm is not None
            else None
        ),
        total_weight_kg=total_weight_kg,
        total_cbm=total_cbm,
        source_span=_find_aggregate_source_span(customer_message),
    )


def _find_aggregate_source_span(customer_message: str) -> str | None:
    candidates: list[tuple[int, str]] = []
    for line in customer_message.splitlines():
        cleaned = line.strip()
        if not cleaned or re.match(r"[a-zA-Z_][a-zA-Z0-9_]*\s*=", cleaned):
            continue
        score = sum(
            bool(re.search(pattern, cleaned, re.IGNORECASE))
            for pattern in (
                PIECE_UNIT_PATTERN,
                r"(?:cbm|m3|m³|volume|vol\.?|meas(?:urement)?|总体积|体积|方|立方)",
                r"(?:kgs?|kg|lbs?|pounds?|gross\s*(?:weight|wt)|g\.?\s*w\.?|总重|重量|毛重)",
            )
        )
        if score:
            candidates.append((score, cleaned[:240]))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def _align_single_parsed_cargo_item_with_explicit_totals(
    cargo_items: list[ExtractedCargoItem],
    *,
    explicit_piece_count: int,
    explicit_weight: Decimal | None,
    explicit_cbm: Decimal | None,
) -> list[ExtractedCargoItem]:
    if len(cargo_items) != 1 or explicit_piece_count <= 1:
        return cargo_items

    item = cargo_items[0]
    updates: dict[str, Any] = {
        "quantity": explicit_piece_count,
        "total_weight_kg": explicit_weight,
        "total_cbm": explicit_cbm,
    }
    if explicit_weight is not None:
        expected_total = item.weight_kg * Decimal(explicit_piece_count) if item.weight_kg is not None else None
        tolerance = max(Decimal("1"), explicit_weight * Decimal("0.05"))
        if expected_total is None or abs(expected_total - explicit_weight) > tolerance:
            updates["weight_kg"] = _quantize(explicit_weight / Decimal(explicit_piece_count), "0.01")

    return [item.model_copy(update=updates)]


def _parse_measurement_line(line: str, *, allow_numeric_table: bool = False) -> list[dict[str, Any]]:
    normalized = _normalize_labeled_dimensions(_normalize_text(line))
    items: list[dict[str, Any]] = []
    dimension_pattern = re.compile(
        rf"(?P<length>{NUMBER_TOKEN_PATTERN})\s*(?P<length_unit>{DIMENSION_UNIT_PATTERN})?\s*"
        r"(?:\*|x|×|by)\s*"
        rf"(?P<width>{NUMBER_TOKEN_PATTERN})\s*(?P<width_unit>{DIMENSION_UNIT_PATTERN})?\s*"
        r"(?:\*|x|×|by)\s*"
        rf"(?P<height>{NUMBER_TOKEN_PATTERN})\s*(?P<height_unit>{DIMENSION_UNIT_PATTERN})?",
        re.IGNORECASE,
    )
    matches = list(dimension_pattern.finditer(normalized))
    for index, match in enumerate(matches):
        next_dimension_start = matches[index + 1].start() if index + 1 < len(matches) else None
        item = _item_from_dimension_match(normalized, match, next_dimension_start=next_dimension_start)
        if item:
            items.append(item)

    if items:
        return items

    space_pattern = re.compile(
        rf"(?<![\d.])(?P<length>{NUMBER_TOKEN_PATTERN})\s+"
        rf"(?P<width>{NUMBER_TOKEN_PATTERN})\s+"
        rf"(?P<height>{NUMBER_TOKEN_PATTERN})(?:\s*(?P<dimension_unit>{DIMENSION_UNIT_PATTERN}))?\s+"
        rf"(?P<weight>{NUMBER_TOKEN_PATTERN})\s*(?P<weight_unit>{WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        re.IGNORECASE,
    )
    match = space_pattern.search(normalized)
    if not match:
        return _parse_numeric_table_measurement_line(normalized) if allow_numeric_table else []
    unit = _resolve_dimension_unit(
        match.group("dimension_unit"),
        match.group("length"),
        match.group("width"),
        match.group("height"),
    )
    return [
        {
            "quantity": Decimal(_find_quantity(normalized, match.start(), match.end())),
            "length_cm": _to_cm(match.group("length"), unit),
            "width_cm": _to_cm(match.group("width"), unit),
            "height_cm": _to_cm(match.group("height"), unit),
            "weight_kg": _to_kg(match.group("weight"), match.group("weight_unit")),
        }
    ]


def _normalize_labeled_dimensions(value: str) -> str:
    number = NUMBER_TOKEN_PATTERN
    unit = DIMENSION_UNIT_PATTERN
    gap = r"[\s,，;；/|*x×-]*"

    lwh_pattern = re.compile(
        rf"\bL\s*/\s*W\s*/\s*H\s*[:：=]?\s*"
        rf"(?P<length>{number})\s*(?:/|\*|x|×)\s*"
        rf"(?P<width>{number})\s*(?:/|\*|x|×)\s*"
        rf"(?P<height>{number})\s*(?P<overall_unit>{unit})?",
        re.IGNORECASE,
    )

    prefix_pattern = re.compile(
        rf"(?:\bL(?:ength)?|长)\s*[:：=]?\s*(?P<length>{number})\s*(?P<length_unit>{unit})?{gap}"
        rf"(?:\bW(?:idth)?|宽)\s*[:：=]?\s*(?P<width>{number})\s*(?P<width_unit>{unit})?{gap}"
        rf"(?:\bH(?:eight)?|高)\s*[:：=]?\s*(?P<height>{number})\s*(?P<height_unit>{unit})?"
        rf"\s*(?P<overall_unit>{unit})?",
        re.IGNORECASE,
    )
    suffix_pattern = re.compile(
        rf"(?P<length>{number})\s*(?P<length_unit>{unit})?\s*[（(]?\s*(?:L|长)\s*[）)]?\s*(?:\*|x|×)\s*"
        rf"(?P<width>{number})\s*(?P<width_unit>{unit})?\s*[（(]?\s*(?:W|宽)\s*[）)]?\s*(?:\*|x|×)\s*"
        rf"(?P<height>{number})\s*(?P<height_unit>{unit})?\s*[（(]?\s*(?:H|高)\s*[）)]?"
        rf"\s*(?P<overall_unit>{unit})?",
        re.IGNORECASE,
    )

    def replace(match: re.Match[str]) -> str:
        overall_unit = match.group("overall_unit") or ""
        dimensions = []
        for name in ("length", "width", "height"):
            number_value = str(_decimal_from_token(match.group(name)))
            number_unit = match.group(f"{name}_unit") or overall_unit
            dimensions.append(f"{number_value}{number_unit}")
        return "x".join(dimensions)

    def replace_lwh(match: re.Match[str]) -> str:
        overall_unit = match.group("overall_unit") or ""
        return "x".join(
            f"{_decimal_from_token(match.group(name))}{overall_unit}"
            for name in ("length", "width", "height")
        )

    normalized = lwh_pattern.sub(replace_lwh, value)
    normalized = prefix_pattern.sub(replace, normalized)
    normalized = suffix_pattern.sub(replace, normalized)

    labeled_value_pattern = re.compile(
        rf"(?P<label>\b(?:L(?:ength)?|W(?:idth)?|H(?:eight)?)\b|长|宽|高)"
        rf"\s*[:：=]?\s*(?P<value>{number})\s*(?P<unit>{unit})?",
        re.IGNORECASE,
    )
    labeled_matches = list(labeled_value_pattern.finditer(normalized))
    labeled_dimensions: dict[str, re.Match[str]] = {}
    for match in labeled_matches:
        label = match.group("label").lower()
        name = "length" if label.startswith("l") or label == "长" else "width" if label.startswith("w") or label == "宽" else "height"
        labeled_dimensions.setdefault(name, match)
    if set(labeled_dimensions) != {"length", "width", "height"}:
        return normalized

    fallback_unit = next(
        (
            match.group("unit")
            for match in reversed(labeled_matches)
            if match.group("unit")
        ),
        "",
    )
    replacement = "x".join(
        f"{_decimal_from_token(labeled_dimensions[name].group('value'))}"
        f"{labeled_dimensions[name].group('unit') or fallback_unit}"
        for name in ("length", "width", "height")
    )
    start = min(match.start() for match in labeled_dimensions.values())
    end = max(match.end() for match in labeled_dimensions.values())
    return f"{normalized[:start]}{replacement}{normalized[end:]}"


def _has_dimension_weight_table(customer_message: str) -> bool:
    normalized = _normalize_text(customer_message).lower()
    return bool(
        re.search(
            r"(?:长|length)\s*(?:宽|width)\s*(?:高|height).*?(?:重量|weight|kg)",
            normalized,
            re.IGNORECASE | re.DOTALL,
        )
        or re.search(r"\bl\b\s*\bw\b\s*\bh\b.*?(?:weight|kg)", normalized, re.IGNORECASE | re.DOTALL)
        or re.search(r"长.{0,20}宽.{0,20}高.{0,40}(?:围长|重量)", normalized, re.IGNORECASE | re.DOTALL)
    )


def _parse_numeric_table_measurement_line(line: str) -> list[dict[str, Any]]:
    if re.search(r"(?:电话|phone|tel|邮编|postal|zip|地址|address|国家|country|城市|city|州省|province)", line, re.IGNORECASE):
        return []

    numbers = [
        Decimal(match.group(0))
        for match in re.finditer(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])", line)
    ]
    if len(numbers) < 4:
        return []

    unit = _resolve_dimension_unit(None, numbers[0], numbers[1], numbers[2])
    length_cm = _to_cm(str(numbers[0]), unit)
    width_cm = _to_cm(str(numbers[1]), unit)
    height_cm = _to_cm(str(numbers[2]), unit)
    weight_kg = numbers[-1] if len(numbers) >= 5 else numbers[3]
    if min(length_cm, width_cm, height_cm, weight_kg) <= 0:
        return []

    return [
        {
            "quantity": Decimal("1"),
            "length_cm": length_cm,
            "width_cm": width_cm,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
        }
    ]


def _item_from_dimension_match(
    line: str,
    match: re.Match[str],
    *,
    next_dimension_start: int | None = None,
) -> dict[str, Any] | None:
    weight = _find_item_weight(line, match.start(), match.end(), next_dimension_start)
    item_end = weight["end"] if weight else match.end()
    quantity = Decimal(_find_quantity(line, match.start(), item_end))
    fallback_unit = _resolve_dimension_unit(
        match.group("height_unit") or match.group("width_unit") or match.group("length_unit"),
        match.group("length"),
        match.group("width"),
        match.group("height"),
    )
    return {
        "quantity": quantity,
        "length_cm": _to_cm(match.group("length"), match.group("length_unit") or fallback_unit),
        "width_cm": _to_cm(match.group("width"), match.group("width_unit") or fallback_unit),
        "height_cm": _to_cm(match.group("height"), match.group("height_unit") or fallback_unit),
        "weight_kg": weight["weight_kg"] if weight else Decimal("0"),
    }


def _find_item_weight(
    line: str,
    dimension_start: int,
    dimension_end: int,
    next_dimension_start: int | None,
) -> dict[str, Any] | None:
    local_limit = next_dimension_start if next_dimension_start is not None else len(line)
    local_weight = _find_weight_in_segment(line[dimension_end:local_limit], offset=dimension_end)
    if local_weight is not None:
        return local_weight

    prefix_start = max(0, dimension_start - 48)
    return _find_weight_in_segment(line[prefix_start:dimension_start], offset=prefix_start)


def _find_weight_in_segment(segment: str, *, offset: int) -> dict[str, Any] | None:
    weight_pattern = re.compile(
        rf"(?P<weight>{NUMBER_TOKEN_PATTERN})\s*(?P<unit>{WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        re.IGNORECASE,
    )
    match = weight_pattern.search(segment)
    if match is None:
        return None
    before_weight = segment[: match.start()]
    if re.search(r"(?:总重|总重量|重量合计|合计|总计)\s*[:：]?\s*$", before_weight, re.IGNORECASE):
        return None
    return {
        "weight_kg": _to_kg(match.group("weight"), match.group("unit")),
        "end": offset + match.end(),
    }


def _find_quantity(line: str, dimension_start: int, item_end: int) -> int:
    prefix = line[max(0, dimension_start - 48) : dimension_start]
    suffix = line[item_end : item_end + 32]
    prefix_labeled_match = re.search(
        rf"(?:qty|quantity|数量|件数)\s*[:：=#-]?\s*(?P<qty>{NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}?[^\d]*$",
        prefix,
        re.IGNORECASE,
    )
    if prefix_labeled_match:
        return max(1, int(_decimal_from_token(prefix_labeled_match.group("qty"))))
    prefix_bare_quantity_match = re.search(
        rf"(?P<qty>{NUMBER_TOKEN_PATTERN})\s*(?:@|x|×)\s*$",
        prefix,
        re.IGNORECASE,
    )
    if prefix_bare_quantity_match:
        return max(1, int(_decimal_from_token(prefix_bare_quantity_match.group("qty"))))
    local_quantity_match = re.search(
        rf"(?P<qty>{NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}",
        line[dimension_start:item_end],
        re.IGNORECASE,
    )
    if local_quantity_match:
        return max(1, int(_decimal_from_token(local_quantity_match.group("qty"))))
    suffix_quantity_match = re.search(
        rf"(?P<qty>{NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}",
        suffix,
        re.IGNORECASE,
    )
    if suffix_quantity_match:
        return max(1, int(_decimal_from_token(suffix_quantity_match.group("qty"))))
    prefix_match = re.search(
        rf"(?P<qty>{NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}\s*$",
        prefix,
        re.IGNORECASE,
    )
    if prefix_match:
        return max(1, int(_decimal_from_token(prefix_match.group("qty"))))
    suffix_match = re.search(
        rf"(?:x|×|qty|quantity|数量|件数)\s*[:：=#-]?\s*(?P<qty>{NUMBER_TOKEN_PATTERN})\b",
        suffix,
        re.IGNORECASE,
    )
    if suffix_match:
        return max(1, int(_decimal_from_token(suffix_match.group("qty"))))
    return 1


def _to_cm(value: str, unit: str | None) -> Decimal:
    number = _decimal_from_token(value)
    normalized = re.sub(r"[.\s]", "", (unit or "cm").strip().lower())
    if normalized in {"mm", "mms", "millimeter", "millimeters", "millimetre", "millimetres", "毫米"}:
        return number / Decimal("10")
    if normalized in {"m", "meter", "meters", "metre", "metres", "米"}:
        return number * Decimal("100")
    if normalized in {"in", "inch", "inches", '"', "英寸"}:
        return number * Decimal("2.54")
    if normalized in {"ft", "foot", "feet", "英尺"}:
        return number * Decimal("30.48")
    return number


def _resolve_dimension_unit(unit: str | None, *values: object) -> str | None:
    if unit:
        return unit
    dimensions = [_decimal_from_token(str(value)) for value in values if value is not None]
    if dimensions and max(dimensions) > Decimal("500"):
        return "mm"
    return None


def _to_kg(value: str, unit: str | None) -> Decimal:
    number = _decimal_from_token(value)
    normalized = re.sub(r"[.\s]", "", (unit or "kg").strip().lower())
    if normalized in {"lb", "lbs", "pound", "pounds", "磅"}:
        return number * Decimal("0.45359237")
    if normalized in {"g", "gram", "grams", "克"}:
        return number / Decimal("1000")
    if normalized in {"mt", "t", "tonne", "tonnes", "metricton", "metrictons", "metrictonne", "metrictonnes"}:
        return number * Decimal("1000")
    return number


def _decimal_from_token(value: str) -> Decimal:
    normalized = value.strip().replace(" ", "")
    if "," in normalized:
        if "." in normalized or len(normalized.rsplit(",", 1)[1]) == 3:
            normalized = normalized.replace(",", "")
        else:
            normalized = normalized.replace(",", ".")
    return Decimal(normalized)


def _to_cbm(value: str, unit: str | None) -> Decimal:
    number = _decimal_from_token(value)
    normalized = re.sub(r"[.\s^]", "", (unit or "cbm").strip().lower())
    if normalized in {"cuft", "cft", "ft3", "cubicfoot", "cubicfeet"}:
        return number * Decimal("0.028316846592")
    if normalized in {"cuin", "cin", "in3", "cubicinch", "cubicinches"}:
        return number * Decimal("0.000016387064")
    if normalized in {"l", "liter", "liters", "litre", "litres"}:
        return number / Decimal("1000")
    return number


def _find_explicit_cbm(customer_message: str) -> Decimal | None:
    normalized = _normalize_text(customer_message)
    labeled_matches = list(
        re.finditer(
            rf"(?<![A-Za-z0-9.])(?P<label>{VOLUME_LABEL_PATTERN})\s*[:：=]?\s*"
            rf"(?P<value>{NUMBER_TOKEN_PATTERN})(?![\d,.])\s*"
            rf"(?P<unit>{VOLUME_UNIT_PATTERN})?(?!\s*(?:\*|x|×|by\b))",
            normalized,
            re.IGNORECASE,
        )
    )
    if labeled_matches:
        match = labeled_matches[-1]
        return _to_cbm(match.group("value"), match.group("unit") or match.group("label"))

    matches = list(
        re.finditer(
            rf"(?P<value>{NUMBER_TOKEN_PATTERN})\s*(?P<unit>{VOLUME_UNIT_PATTERN})(?=$|[^A-Za-z])",
            normalized,
            re.IGNORECASE,
        )
    )
    return _to_cbm(matches[-1].group("value"), matches[-1].group("unit")) if matches else None


def _find_authoritative_weight(customer_message: str) -> Decimal | None:
    normalized = _normalize_text(customer_message)
    patterns = [
        rf"{TOTAL_WEIGHT_LABEL_PATTERN}\s*[:：=#-]?\s*({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"(?:合计|总计|一共)\s*[:：]?\s*(?:总?重(?:量)?|毛重)?\s*({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})\s*(?:total|gross|合计|总重)",
    ]
    values = {
        _to_kg(match.group(1), match.group(2))
        for pattern in patterns
        for match in re.finditer(pattern, normalized, re.IGNORECASE)
    }
    return next(iter(values)) if len(values) == 1 else None


def _find_explicit_weight(customer_message: str) -> Decimal | None:
    normalized = _normalize_text(customer_message)
    patterns = [
        rf"{TOTAL_WEIGHT_LABEL_PATTERN}\s*[:：=#-]?\s*({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"(?:weight|wt|重量|毛重)\s*[:：=]\s*(?:total|gross|共|合计|总计)?\s*"
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"(?:合计|总计|一共|共)\s*[:：]?\s*(?:总?重(?:量)?|毛重)?\s*"
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})\s*(?:total|gross|合计|总重)",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, normalized, re.IGNORECASE):
            if not _is_per_piece_weight_context(normalized, match.start(), match.end()):
                return _to_kg(match.group(1), match.group(2))
    return None


def _find_per_piece_weight(customer_message: str) -> Decimal | None:
    normalized = _normalize_text(customer_message)
    item_name = rf"(?:{PIECE_UNIT_PATTERN}|pc|ctn|pkg|plt)"
    patterns = [
        rf"(?:单|每)(?:件|箱|包|袋|卷|桶|托|托盘)(?:毛重|重量|重)?\s*[:：=]?\s*"
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"(?:weight\s*)?(?:each|per\s*{item_name})\s*[:：=]?\s*"
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
        rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})\s*"
        rf"(?:each|ea\.?|per\s*{item_name}|/\s*(?:ea\.?|{item_name})|每(?:件|箱|包|袋|卷|桶|托|托盘))",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return _to_kg(match.group(1), match.group(2))
    return None


def _is_per_piece_weight_context(value: str, start: int, end: int) -> bool:
    context = value[max(0, start - 24) : min(len(value), end + 24)]
    return bool(
        re.search(
            r"(?:\beach\b|\bea\.?\b|\bper\s*(?:piece|carton|box|package|case|bag|skid|pallet)\b|"
            r"/\s*(?:ea\.?|pc|ctn|pkg|plt)\b|单(?:件|箱|包|袋|卷|桶|托)|每(?:件|箱|包|袋|卷|桶|托))",
            context,
            re.IGNORECASE,
        )
    )


def _find_any_weight(customer_message: str) -> Decimal | None:
    normalized = _normalize_text(customer_message)
    matches = list(
        re.finditer(
            rf"({NUMBER_TOKEN_PATTERN})\s*({WEIGHT_UNIT_PATTERN})(?=$|[^A-Za-z])",
            normalized,
            re.IGNORECASE,
        )
    )
    if not matches:
        return None
    match = matches[-1]
    return _to_kg(match.group(1), match.group(2))


def _find_authoritative_piece_count(customer_message: str) -> int | None:
    normalized = _normalize_text(customer_message)
    patterns = [
        rf"{PIECE_COUNT_LABEL_PATTERN}\s*[:：=#-]?\s*(?:共|合计|总计)?\s*"
        rf"({NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}?",
        rf"(?:一共|共|合计|总计)\s*({NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}",
        rf"({NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}\s*(?:total|合计|总计)",
    ]
    values = {
        int(_decimal_from_token(match.group(1)))
        for pattern in patterns
        for match in re.finditer(pattern, normalized, re.IGNORECASE)
    }
    return next(iter(values)) if len(values) == 1 else None


def _find_explicit_piece_count(customer_message: str) -> int | None:
    normalized = _normalize_text(customer_message)
    patterns = [
        rf"{PIECE_COUNT_LABEL_PATTERN}\s*[:：=#-]?\s*(?:共|合计|总计)?\s*"
        rf"({NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}?",
        rf"(?:pieces?|packages?|pkgs?|ctns?|cartons?|boxes|件数|总件数|共|一共|合计|总计)"
        rf"[^\d\n\r]{{0,8}}({NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}",
        rf"({NUMBER_TOKEN_PATTERN})\s*{PIECE_UNIT_PATTERN}\s*(?:total|合计|共)?",
        rf"(?:ctns?|cartons?|pkgs?|packages?|pcs?|pieces?|skids?|skds?|pallets?|plts?)"
        rf"\s*[:：=#-]?\s*({NUMBER_TOKEN_PATTERN})\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, normalized, re.IGNORECASE)
        if match:
            return max(1, int(_decimal_from_token(match.group(1))))
    return _find_explicit_pallet_count(customer_message)


def _find_explicit_pallet_count(customer_message: str) -> int | None:
    normalized = _normalize_text(customer_message)
    match = re.search(
        rf"({NUMBER_TOKEN_PATTERN})\s*(?:托盘|托|pallets?\b|skids?\b|skds?\b|plts?\b)",
        normalized,
        re.IGNORECASE,
    )
    return max(1, int(_decimal_from_token(match.group(1)))) if match else None


def _find_postal_code(customer_message: str) -> str | None:
    match = POSTAL_CODE_PATTERN.search(customer_message)
    if not match:
        return None
    compact = re.sub(r"[^A-Za-z0-9]", "", match.group(0)).upper()
    return f"{compact[:3]} {compact[3:]}" if len(compact) == 6 else match.group(0).upper()


def _find_province(customer_message: str) -> str | None:
    normalized = _normalize_text(customer_message).lower()
    for alias, code in sorted(PROVINCE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"(^|[^a-z0-9]){re.escape(alias)}([^a-z0-9]|$)", normalized):
            return code
    return None


def _parse_confirmed_fields(customer_message: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    allowed = {
        "address_line",
        "postal_code",
        "city",
        "province",
        "packaging_type",
        "address_type",
        "requires_liftgate",
        "requires_pallet_jack",
        "requires_appointment",
        "detention_minutes",
        "explicit_pallet_count",
        "is_stackable",
    }
    for line in customer_message.splitlines():
        match = re.match(r"\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and match.group(1) in allowed:
            fields[match.group(1)] = match.group(2)
    return fields


def _apply_confirmed_fields(draft: AIExtractedQuoteDraft, fields: dict[str, str]) -> None:
    if not fields:
        return
    if "address_line" in fields:
        draft.address_line = fields["address_line"] or draft.address_line
    if "postal_code" in fields:
        draft.postal_code = _find_postal_code(fields["postal_code"]) or draft.postal_code
    if "city" in fields:
        draft.city = fields["city"] or draft.city
    if "province" in fields:
        draft.province = _find_province(fields["province"]) or fields["province"].upper() or draft.province
    if "packaging_type" in fields:
        draft.packaging_type = fields["packaging_type"].strip().lower() or draft.packaging_type
    if "address_type" in fields:
        draft.address_type = fields["address_type"].strip().lower() or draft.address_type
    if "requires_liftgate" in fields:
        draft.requires_liftgate = _coerce_bool(fields["requires_liftgate"], default=draft.requires_liftgate)
    if "requires_pallet_jack" in fields:
        draft.requires_pallet_jack = _coerce_bool(fields["requires_pallet_jack"], default=draft.requires_pallet_jack)
    if "requires_appointment" in fields:
        draft.requires_appointment = _coerce_bool(fields["requires_appointment"], default=draft.requires_appointment)
    if "detention_minutes" in fields:
        draft.detention_minutes = _coerce_int(fields["detention_minutes"], default=draft.detention_minutes)
    if "explicit_pallet_count" in fields:
        draft.explicit_pallet_count = _coerce_optional_int(fields["explicit_pallet_count"])
    if "is_stackable" in fields:
        draft.is_stackable = _coerce_bool(fields["is_stackable"], default=False)


def _parse_address_fields(customer_message: str) -> dict[str, str | None]:
    labeled_fields = _parse_labeled_address_fields(customer_message)
    lines = [_clean_address_line(line) for line in customer_message.splitlines()]
    lines = [line for line in lines if line and not _is_non_address_line(line)]
    postal_code = labeled_fields["postal_code"] or _find_postal_code(customer_message)
    province = labeled_fields["province"] or _find_province(customer_message)
    address_line: str | None = labeled_fields["address_line"]
    city: str | None = labeled_fields["city"]

    for index, line in enumerate(lines):
        if not city and (_find_postal_code(line) or _find_province(line)):
            parsed = _parse_city_from_address_line(line)
            if parsed["address_line"] and not address_line:
                address_line = parsed["address_line"]
            if parsed["city"]:
                city = parsed["city"]

        if not address_line and _looks_like_street_address(line):
            address_line = _strip_postal_province_country(line)

        if not city and address_line and index > 0:
            maybe_city = _parse_city_from_address_line(line)["city"]
            if maybe_city:
                city = maybe_city

    return {
        "address_line": address_line,
        "city": city,
        "province": province,
        "postal_code": postal_code,
    }


def _parse_labeled_address_fields(customer_message: str) -> dict[str, str | None]:
    fields: dict[str, str | None] = {
        "address_line": None,
        "city": None,
        "province": None,
        "postal_code": None,
    }
    for line in customer_message.splitlines():
        match = re.match(r"\s*(?P<label>[^:：]{1,24})\s*[:：]\s*(?P<value>.+?)\s*$", line)
        if not match:
            continue
        label = match.group("label").strip().lower()
        value = match.group("value").strip()
        if not value:
            continue
        if re.search(r"(?:地址\s*\d*|address\s*(?:line)?\s*\d*)$", label, re.IGNORECASE):
            parsed = _parse_city_from_address_line(value)
            fields["address_line"] = parsed["address_line"] or _strip_postal_province_country(value) or value
            if parsed["city"] and not fields["city"]:
                fields["city"] = parsed["city"]
            if _find_province(value) and not fields["province"]:
                fields["province"] = _find_province(value)
            if _find_postal_code(value) and not fields["postal_code"]:
                fields["postal_code"] = _find_postal_code(value)
        elif re.search(r"(?:城市|city)$", label, re.IGNORECASE):
            fields["city"] = value
        elif re.search(r"(?:州省|省份|province|state)$", label, re.IGNORECASE):
            fields["province"] = _find_province(value) or value.upper()
        elif re.search(r"(?:邮编|postal|zip)", label, re.IGNORECASE):
            fields["postal_code"] = _find_postal_code(value)
    return fields


def _clean_address_line(line: str) -> str:
    cleaned = line.strip()
    cleaned = re.sub(r"^加拿大地址\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(?:地址\s*\d*|收件地址|目的地|派送地址|delivery\s*address|address\s*(?:line)?\s*\d*)\s*[:：]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^\d{1,5}\s*(?:件|箱|pcs?|pieces?|ctns?|cartons?|boxes)\s*(?:货|货物|cargo|goods)?[.。,\s，]*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"@[\w\-\u4e00-\u9fff()（）]+", "", cleaned).strip()
    return cleaned


def _is_non_address_line(line: str) -> bool:
    if _find_postal_code(line) or _looks_like_street_address(line):
        return False
    lowered = line.lower()
    if re.match(r"[a-zA-Z_][a-zA-Z0-9_]*\s*=", line):
        return True
    if re.search(r"(?:hscode|hs\s*code|品名|产品|商品)", lowered, re.IGNORECASE):
        return True
    if re.search(r"(?:cbm|m3|m³|kg|kgs|公斤|千克|箱|件|品名|报价|谢谢|麻烦)", lowered, re.IGNORECASE):
        return True
    return False


def _looks_like_street_address(line: str) -> bool:
    if re.search(r"(?:cbm|m3|m³|kg|kgs|公斤|千克|箱|件)", line, flags=re.IGNORECASE):
        return False
    if re.search(r"\d+(?:\.\d+)?\s*(?:mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸)?\s*(?:\*|x|×|by)\s*\d+(?:\.\d+)?", line, flags=re.IGNORECASE):
        return False
    return bool(re.search(r"\b\d{1,6}\b", line) and re.search(r"[A-Za-z]", line))


def _parse_city_from_address_line(line: str) -> dict[str, str | None]:
    without_postal = POSTAL_CODE_PATTERN.sub(" ", line)
    province_match = _find_province_match(without_postal)
    if province_match:
        before_province = without_postal[: province_match.start()].strip(" ,，")
    else:
        before_province = without_postal
    before_province = _remove_country_aliases(before_province).strip(" ,，")
    if not before_province:
        return {"address_line": None, "city": None}

    parts = [part.strip(" ,，") for part in re.split(r"[,，]", before_province) if part.strip(" ,，")]
    if len(parts) >= 2:
        if not province_match and _looks_like_street_address(parts[-1]):
            return {"address_line": _join_unique_parts(parts), "city": None}
        return {"address_line": ", ".join(parts[:-1]), "city": parts[-1]}
    if province_match and _looks_like_street_address(before_province):
        split = _split_trailing_city_from_street(before_province)
        if split["city"]:
            return split
    if not _looks_like_street_address(before_province):
        return {"address_line": None, "city": before_province}
    return {"address_line": before_province, "city": None}


def _split_trailing_city_from_street(value: str) -> dict[str, str | None]:
    street_pattern = re.compile(
        r"^(?P<address>.+?\b(?:range\s+road|road|rd|street|st|avenue|ave|boulevard|blvd|drive|dr|way|parkway|pkwy|lane|ln|route|hwy|highway)\b(?:\s+\d+[A-Za-z]?)?(?:\s*(?:#|unit|suite|ste)\s*[\w-]+)?)\s+(?P<city>[A-Za-z][A-Za-z .'-]{2,})$",
        re.IGNORECASE,
    )
    match = street_pattern.match(value.strip())
    if not match:
        return {"address_line": value, "city": None}
    city = match.group("city").strip(" ,，")
    if _looks_like_street_address(city):
        return {"address_line": value, "city": None}
    return {"address_line": match.group("address").strip(" ,，"), "city": city}


def _join_unique_parts(parts: list[str]) -> str:
    unique: list[str] = []
    seen: set[str] = set()
    for part in parts:
        key = part.strip().lower()
        if key not in seen:
            seen.add(key)
            unique.append(part)
    return ", ".join(unique)


def _find_province_match(value: str) -> re.Match[str] | None:
    normalized = _normalize_text(value)
    for alias, _code in sorted(PROVINCE_ALIASES.items(), key=lambda item: len(item[0]), reverse=True):
        match = re.search(rf"(^|[^a-z0-9]){re.escape(alias)}([^a-z0-9]|$)", normalized, flags=re.IGNORECASE)
        if match:
            return match
    return None


def _strip_postal_province_country(value: str) -> str:
    cleaned = POSTAL_CODE_PATTERN.sub(" ", value)
    province_match = _find_province_match(cleaned)
    if province_match:
        cleaned = cleaned[: province_match.start()]
    return _remove_country_aliases(cleaned).strip(" ,，")


def _remove_country_aliases(value: str) -> str:
    cleaned = value
    for country in ("canada", "加拿大"):
        cleaned = re.sub(rf"(^|[^a-z0-9]){re.escape(country)}([^a-z0-9]|$)", " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned)


def _infer_packaging_type(customer_message: str) -> str | None:
    lowered = customer_message.lower()
    if re.search(r"木箱|wooden\s*crate|crate", lowered):
        return "wooden_crate"
    if re.search(r"托盘|pallet|skid|\bplts?\b", lowered):
        return "pallet"
    if re.search(r"编织袋|woven\s*bag", lowered):
        return "woven_bag"
    if re.search(r"软包|软包装|flexible", lowered):
        return "flexible_packaging"
    if re.search(r"纸箱|carton|ctn|box|boxes|箱", lowered):
        return "carton"
    return "unknown"


def _normalize_text(value: str) -> str:
    return (
        unicodedata.normalize("NFKC", value)
        .replace("＊", "*")
        .replace("Ｘ", "x")
        .replace("×", "×")
        .replace("磅", " lb")
        .replace("公斤", " kg")
        .replace("千克", " kg")
        .replace("厘米", " cm")
    )


def _quantize(value: Decimal | None, exponent: str) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal(exponent))
