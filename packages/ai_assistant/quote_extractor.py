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
ALLOWED_PACKAGING_TYPES = {"carton", "wooden_crate", "pallet", "woven_bag", "flexible_packaging"}
ALLOWED_ADDRESS_TYPES = {"commercial", "residential", "private", "rural_residential"}


def extract_quote_draft(customer_message: str, client: BaseAIClient) -> AIExtractedQuoteDraft:
    response = client.complete(
        [
            AIMessage(role="system", content=FIELD_EXTRACTION_SYSTEM_PROMPT),
            AIMessage(role="user", content=customer_message),
        ]
    )
    if response.error:
        raise QuoteExtractionError(response.error)
    data = _parse_json_object(response.content)
    draft = AIExtractedQuoteDraft.model_validate(data)
    draft.missing_fields = sorted(set(draft.missing_fields) | missing_required_fields(draft))
    return draft


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
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise QuoteExtractionError("AI extraction did not return valid JSON.") from exc
    if not isinstance(data, dict):
        raise QuoteExtractionError("AI extraction JSON must be an object.")
    return data
