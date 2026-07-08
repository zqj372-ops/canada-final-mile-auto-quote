from __future__ import annotations

from decimal import Decimal
import json
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.ai_assistant.model_client import AIMessage, BaseAIClient
from packages.ai_assistant.prompts import FIELD_EXTRACTION_SYSTEM_PROMPT


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

    @field_validator("packaging_type")
    @classmethod
    def normalize_packaging_type(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value

    @field_validator("address_type")
    @classmethod
    def normalize_address_type(cls, value: str | None) -> str | None:
        return value.strip().lower() if value else value


class QuoteExtractionError(Exception):
    pass


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
    response = client.complete(
        [
            AIMessage(role="system", content=FIELD_EXTRACTION_SYSTEM_PROMPT),
            AIMessage(role="user", content=customer_message),
        ]
    )
    if response.error:
        raise QuoteExtractionError(response.error)
    data = _sanitize_extraction_data(_parse_json_object(response.content))
    draft = AIExtractedQuoteDraft.model_validate(data)
    draft = apply_deterministic_extraction(draft, customer_message)
    draft.missing_fields = sorted(missing_required_fields(draft))
    return draft


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
    return draft


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
    return normalized


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
            total_cbm += (length_cm * width_cm * height_cm / Decimal("1000000")) * quantity
            total_weight_kg += weight_kg * quantity
            piece_count += int(quantity)
            line_longest = max(length_cm, width_cm, height_cm)
            longest_side_cm = line_longest if longest_side_cm is None else max(longest_side_cm, line_longest)

    explicit_cbm = _find_explicit_decimal(customer_message, r"(?:cbm|m3|m³|方|立方)")
    explicit_piece_count = _find_explicit_piece_count(customer_message)
    explicit_weight = _find_explicit_weight(customer_message)
    if explicit_weight is None and explicit_piece_count is not None and explicit_cbm is not None:
        explicit_weight = _find_any_weight(customer_message)

    if explicit_cbm is not None:
        total_cbm = explicit_cbm
    if explicit_weight is not None:
        total_weight_kg = explicit_weight
    if explicit_piece_count is not None and explicit_piece_count >= piece_count:
        piece_count = explicit_piece_count

    return {
        "piece_count": piece_count,
        "cbm": _quantize(total_cbm, "0.001") if total_cbm > 0 else None,
        "weight_kg": _quantize(total_weight_kg, "0.1") if total_weight_kg > 0 else None,
        "longest_side_cm": _quantize(longest_side_cm, "0.1") if longest_side_cm is not None else None,
        "notes": (
            f"Deterministic parser normalized {piece_count} piece(s) from {parsed_lines} cargo line(s)."
            if piece_count
            else None
        ),
    }


def _parse_measurement_line(line: str, *, allow_numeric_table: bool = False) -> list[dict[str, Any]]:
    normalized = _normalize_text(line)
    items: list[dict[str, Any]] = []
    dimension_pattern = re.compile(
        r"(?P<length>\d+(?:\.\d+)?)\s*(?P<length_unit>mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸)?\s*"
        r"(?:\*|x|×|by)\s*"
        r"(?P<width>\d+(?:\.\d+)?)\s*(?P<width_unit>mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸)?\s*"
        r"(?:\*|x|×|by)\s*"
        r"(?P<height>\d+(?:\.\d+)?)\s*(?P<height_unit>mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸)?",
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
        r"(?<![\d.])(?P<length>\d+(?:\.\d+)?)\s+"
        r"(?P<width>\d+(?:\.\d+)?)\s+"
        r"(?P<height>\d+(?:\.\d+)?)(?:\s*(?P<dimension_unit>mm|cm|厘米|m|米|inches|inch|in|\"|ft|feet|英尺|英寸))?\s+"
        r"(?P<weight>\d+(?:\.\d+)?)\s*(?P<weight_unit>kgs?|kg|公斤|千克|lbs?|pounds?|磅|g|grams?|克)(?=$|[^A-Za-z])",
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
        r"(?P<weight>\d+(?:\.\d+)?)\s*(?P<unit>kgs?|kg|公斤|千克|lbs?|pounds?|磅|g|grams?|克)(?=$|[^A-Za-z])",
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
    prefix = line[max(0, dimension_start - 24) : dimension_start]
    suffix = line[item_end : item_end + 32]
    suffix_quantity_match = re.search(
        r"(?P<qty>\d{1,5})\s*(?:pcs?|pieces?|ctns?|cartons?|boxes|箱|件|托|pallets?)",
        suffix,
        re.IGNORECASE,
    )
    if suffix_quantity_match:
        return max(1, int(suffix_quantity_match.group("qty")))
    prefix_match = re.search(
        r"(?P<qty>\d{1,5})\s*(?:pcs?|pieces?|ctns?|cartons?|boxes|箱|件|托|pallets?)\s*$",
        prefix,
        re.IGNORECASE,
    )
    if prefix_match:
        return max(1, int(prefix_match.group("qty")))
    suffix_match = re.search(
        r"(?:x|×|qty|quantity|数量|件数)\s*(?P<qty>\d{1,5})\b",
        suffix,
        re.IGNORECASE,
    )
    if suffix_match:
        return max(1, int(suffix_match.group("qty")))
    return 1


def _to_cm(value: str, unit: str | None) -> Decimal:
    number = Decimal(value)
    normalized = (unit or "cm").strip().lower()
    if normalized in {"mm"}:
        return number / Decimal("10")
    if normalized in {"m", "米"}:
        return number * Decimal("100")
    if normalized in {"in", "inch", "inches", '"', "英寸"}:
        return number * Decimal("2.54")
    if normalized in {"ft", "feet", "英尺"}:
        return number * Decimal("30.48")
    return number


def _resolve_dimension_unit(unit: str | None, *values: object) -> str | None:
    if unit:
        return unit
    dimensions = [Decimal(str(value)) for value in values if value is not None]
    if dimensions and max(dimensions) > Decimal("500"):
        return "mm"
    return None


def _to_kg(value: str, unit: str | None) -> Decimal:
    number = Decimal(value)
    normalized = (unit or "kg").strip().lower()
    if normalized in {"lb", "lbs", "pound", "pounds", "磅"}:
        return number * Decimal("0.45359237")
    if normalized in {"g", "gram", "grams", "克"}:
        return number / Decimal("1000")
    return number


def _find_explicit_decimal(customer_message: str, unit_pattern: str) -> Decimal | None:
    match = re.search(rf"(\d+(?:\.\d+)?)\s*{unit_pattern}\b", customer_message, re.IGNORECASE)
    return Decimal(match.group(1)) if match else None


def _find_explicit_weight(customer_message: str) -> Decimal | None:
    patterns = [
        r"(?:total\s*weight|总重量|总重|重量合计)\D{0,12}(\d+(?:\.\d+)?)\s*(kgs?|kg|公斤|千克|lbs?|pounds?|磅|g|grams?|克)\b",
        r"(?:合计|总计|一共|共)[^\n\r]{0,32}?(\d+(?:\.\d+)?)\s*(kgs?|kg|公斤|千克|lbs?|pounds?|磅|g|grams?|克)\b",
        r"(\d+(?:\.\d+)?)\s*(kgs?|kg|公斤|千克|lbs?|pounds?|磅|g|grams?|克)\s*(?:total|合计|总重)",
    ]
    for pattern in patterns:
        match = re.search(pattern, customer_message, re.IGNORECASE)
        if match:
            return _to_kg(match.group(1), match.group(2))
    return None


def _find_any_weight(customer_message: str) -> Decimal | None:
    matches = list(
        re.finditer(
            r"(\d+(?:\.\d+)?)\s*(kgs?|kg|公斤|千克|lbs?|pounds?|磅|g|grams?|克)\b",
            customer_message,
            re.IGNORECASE,
        )
    )
    if not matches:
        return None
    match = matches[-1]
    return _to_kg(match.group(1), match.group(2))


def _find_explicit_piece_count(customer_message: str) -> int | None:
    patterns = [
        r"(?:数量|箱数|件数|总件数|总箱数)\s*[:：]?\s*(?:共|合计|总计)?\s*(\d{1,4})\s*(?:pcs?|pieces?|件|箱|ctns?|cartons?|boxes)",
        r"(?:piece_count|pieces?|件数|总件数|共|一共|合计|总计)[^\d\n\r]{0,8}(\d{1,4})\s*(?:pcs?|pieces?|件|箱|ctns?|cartons?|boxes)",
        r"(\d{1,4})\s*(?:pcs?|pieces?|件|箱|ctns?)\s*(?:total|合计|共)?",
    ]
    for pattern in patterns:
        match = re.search(pattern, customer_message, re.IGNORECASE)
        if match:
            return max(1, int(match.group(1)))
    return None


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
    if not _looks_like_street_address(before_province):
        return {"address_line": None, "city": before_province}
    return {"address_line": before_province, "city": None}


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
    if re.search(r"托盘|pallet", lowered):
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
        value.replace("＊", "*")
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
