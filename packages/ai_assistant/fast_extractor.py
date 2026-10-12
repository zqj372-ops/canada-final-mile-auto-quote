"""A conservative zero-model path for a single, explicitly labelled shipment.

Every non-empty line must match the grammar. Conversation, corrections, multiple
shipments and mixed packaging deliberately fall through to the model extractor.
This is an extraction optimization, never a pricing implementation.
"""
from __future__ import annotations

import re

from packages.ai_assistant.service_requirements import SERVICE_FIELDS
from packages.address_normalizer import normalize_postal_code, normalize_province
from packages.ai_assistant.quote_extractor import (
    AIExtractedQuoteDraft,
    apply_deterministic_extraction,
    missing_required_fields,
)

_NUMBER = r"\d+(?:\.\d+)?"
_DIMENSIONS = re.compile(
    rf"{_NUMBER}\s*[*x×]\s*{_NUMBER}\s*[*x×]\s*{_NUMBER}\s*(?:cm|mm|in|inch|inches|ft|厘米|毫米|英寸|英尺)",
    re.I,
)
_PACKAGES = {
    "托盘": "pallet", "pallet": "pallet", "pallets": "pallet",
    "纸箱": "carton", "carton": "carton", "cartons": "carton",
    "木箱": "wooden_crate", "crate": "wooden_crate", "crates": "wooden_crate",
}
_ADDRESS_TYPES = {
    "商业地址": "commercial", "commercial": "commercial",
    "住宅地址": "residential", "residential": "residential",
    "私人地址": "private", "private": "private",
}
_LABELS = {
    "地址": "address_line", "街道地址": "address_line", "address": "address_line",
    "城市": "city", "city": "city", "省份": "province", "province": "province",
    "邮编": "postal_code", "postal code": "postal_code",
    "地址类型": "address_type", "address type": "address_type",
    "数量": "quantity", "quantity": "quantity",
    "尺寸": "dimensions", "dimensions": "dimensions",
    "总重": "weight", "total weight": "weight",
    "总体积": "volume", "total volume": "volume",
    "尾板": "requires_liftgate", "liftgate": "requires_liftgate",
    "手叉车": "requires_pallet_jack", "pallet jack": "requires_pallet_jack",
    "预约": "requires_appointment", "appointment": "requires_appointment",
    "可堆叠": "is_stackable", "stackable": "is_stackable",
    "等待时间": "detention_minutes", "detention minutes": "detention_minutes",
}
_BOOL = {"是": True, "需要": True, "yes": True, "true": True,
         "否": False, "不需要": False, "no": False, "false": False}


def try_extract_locally(message: str) -> AIExtractedQuoteDraft | None:
    fields: dict[str, str] = {}
    for line in message.splitlines():
        if not line.strip():
            continue
        match = re.fullmatch(r"\s*([^:：]+)\s*[:：]\s*(.+?)\s*", line)
        if not match:
            return None
        key = _LABELS.get(match[1].strip().lower())
        if key is None or key in fields:
            return None
        fields[key] = match[2].strip()

    required = {"address_line", "city", "province", "postal_code", "address_type", "quantity", "weight"}
    if not required.issubset(fields) or not ({"dimensions", "volume"} & fields.keys()):
        return None
    # Restrict address values to literal street/city fields, not embedded instructions.
    if not re.fullmatch(r"[\w .,'’#/-]+", fields["address_line"], re.ASCII):
        return None
    if not re.search(r"\d", fields["address_line"]):
        return None
    if not re.fullmatch(r"[A-Za-zÀ-ÿ .’'-]+", fields["city"]):
        return None
    postal = normalize_postal_code(fields["postal_code"])
    province = normalize_province(fields["province"])
    address_type = _ADDRESS_TYPES.get(fields["address_type"].lower())
    quantity = re.fullmatch(r"([1-9]\d*)\s*(托盘|纸箱|木箱|pallets?|cartons?|crates?)", fields["quantity"], re.I)
    if not postal or not province or not address_type or not quantity:
        return None
    if "dimensions" in fields and not _DIMENSIONS.fullmatch(fields["dimensions"]):
        return None
    if not re.fullmatch(rf"{_NUMBER}\s*(?:kg|kgs|lb|lbs|公斤|千克|磅)", fields["weight"], re.I):
        return None
    if "volume" in fields and not re.fullmatch(rf"{_NUMBER}\s*(?:cbm|m3|m³|立方米)", fields["volume"], re.I):
        return None

    draft = AIExtractedQuoteDraft(
        address_line=fields["address_line"], city=fields["city"],
        province=province, postal_code=postal, address_type=address_type,
        packaging_type=_PACKAGES[quantity[2].lower()],
    )
    for key in ("requires_liftgate", "requires_pallet_jack", "requires_appointment", "is_stackable"):
        if key in fields:
            value = _BOOL.get(fields[key].lower())
            if value is None:
                return None
            setattr(draft, key, value)
    if "detention_minutes" in fields:
        if not re.fullmatch(r"\d{1,4}", fields["detention_minutes"]):
            return None
        draft.detention_minutes = int(fields["detention_minutes"])
    draft = apply_deterministic_extraction(draft, message)
    if ((missing_required_fields(draft) - set(SERVICE_FIELDS)) or draft.piece_count != int(quantity[1])
            or not draft.cbm or not draft.weight_kg
            or any("mismatch" in note for note in draft.validation_notes)):
        return None
    draft.validation_notes.append("local_labelled_extraction")
    draft.missing_fields = sorted(missing_required_fields(draft))
    return draft
