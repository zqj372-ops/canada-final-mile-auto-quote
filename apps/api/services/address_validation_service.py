from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from apps.api.db.repositories.zone_repository import ZoneRepository
from packages.address_normalizer import clean_address, normalize_city, normalize_postal_code, normalize_province
from packages.ai_assistant.quote_extractor import AIExtractedQuoteDraft
from packages.quote_engine.zone_lookup import get_province_from_postal_code


AddressValidationStatus = Literal[
    "missing_postal_code",
    "invalid_postal_code",
    "postal_not_found",
    "postal_verified",
    "verified",
    "corrected_by_postal_lookup",
]


class LocalAddressValidation(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str = "local_postal_code_city_lookup"
    status: AddressValidationStatus
    matched: bool
    confidence: int = Field(ge=0, le=100)
    address_line: str | None = None
    postal_code: str | None = None
    postal_prefix: str | None = None
    input_city: str | None = None
    input_province: str | None = None
    preferred_city: str | None = None
    official_city: str | None = None
    municipality: str | None = None
    province: str | None = None
    corrected_city: str | None = None
    corrected_province: str | None = None
    city_consistent: bool | None = None
    province_consistent: bool | None = None
    latitude: float | None = None
    longitude: float | None = None
    source: str | None = None
    risk_tags: list[str] = Field(default_factory=list)
    note_zh: str


def build_local_address_validation(
    db: Session,
    *,
    address_line: str | None,
    postal_code: str | None,
    city: str | None,
    province: str | None,
) -> LocalAddressValidation:
    cleaned_address = clean_address(address_line)
    normalized_postal = normalize_postal_code(postal_code)
    normalized_city = normalize_city(city)
    normalized_province = normalize_province(province)

    if not postal_code:
        return LocalAddressValidation(
            status="missing_postal_code",
            matched=False,
            confidence=0,
            address_line=cleaned_address,
            input_city=normalized_city,
            input_province=normalized_province,
            risk_tags=["postal_code_missing"],
            note_zh="未提供加拿大邮编，本地邮编库无法验证地址城市和省份。",
        )

    if normalized_postal is None:
        return LocalAddressValidation(
            status="invalid_postal_code",
            matched=False,
            confidence=0,
            address_line=cleaned_address,
            input_city=normalized_city,
            input_province=normalized_province,
            risk_tags=["postal_code_invalid"],
            note_zh=f"邮编 {postal_code} 格式无法识别，请人工确认加拿大邮编。",
        )

    repository = ZoneRepository(db)
    record = repository.get_preferred_city(normalized_postal)
    postal_prefix = normalized_postal[:3]
    province_from_postal = get_province_from_postal_code(normalized_postal)

    if record is None:
        return LocalAddressValidation(
            status="postal_not_found",
            matched=False,
            confidence=25,
            address_line=cleaned_address,
            postal_code=normalized_postal,
            postal_prefix=postal_prefix,
            input_city=normalized_city,
            input_province=normalized_province,
            province=province_from_postal,
            risk_tags=["postal_lookup_not_found"],
            note_zh=(
                f"本地邮编库未找到 {normalized_postal} 的城市记录。"
                "地图仅供人工目视确认，系统不能用地图结果覆盖价格规则。"
            ),
        )

    preferred_city = normalize_city(record.preferred_city) or record.preferred_city
    record_province = normalize_province(record.province) or record.province or province_from_postal
    canonical_input_city = repository.resolve_city_alias(normalized_city, record_province)
    city_consistent = None if not normalized_city else canonical_input_city == preferred_city
    province_consistent = None if not normalized_province else normalized_province == record_province
    needs_correction = city_consistent is False or province_consistent is False

    risk_tags = ["local_postal_verified"]
    if city_consistent is False:
        risk_tags.append("city_corrected_by_postal_lookup")
    if province_consistent is False:
        risk_tags.append("province_corrected_by_postal_lookup")

    status: AddressValidationStatus
    if needs_correction:
        status = "corrected_by_postal_lookup"
        confidence = 72
    elif normalized_city or normalized_province:
        status = "verified"
        confidence = 95
    else:
        status = "postal_verified"
        confidence = 88

    note_zh = _build_note(
        postal_code=normalized_postal,
        preferred_city=preferred_city,
        province=record_province,
        city_consistent=city_consistent,
        province_consistent=province_consistent,
    )

    return LocalAddressValidation(
        status=status,
        matched=True,
        confidence=confidence,
        address_line=cleaned_address,
        postal_code=normalized_postal,
        postal_prefix=postal_prefix,
        input_city=normalized_city,
        input_province=normalized_province,
        preferred_city=preferred_city,
        official_city=normalize_city(record.official_city),
        municipality=normalize_city(record.municipality),
        province=record_province,
        corrected_city=preferred_city if city_consistent is False else None,
        corrected_province=record_province if province_consistent is False else None,
        city_consistent=city_consistent,
        province_consistent=province_consistent,
        latitude=float(record.latitude) if record.latitude is not None else None,
        longitude=float(record.longitude) if record.longitude is not None else None,
        source=record.source,
        risk_tags=risk_tags,
        note_zh=note_zh,
    )


def build_local_address_validation_from_extraction(
    db: Session,
    extraction: AIExtractedQuoteDraft,
) -> LocalAddressValidation:
    return build_local_address_validation(
        db,
        address_line=extraction.address_line,
        postal_code=extraction.postal_code,
        city=extraction.city,
        province=extraction.province,
    )


def _build_note(
    *,
    postal_code: str,
    preferred_city: str,
    province: str | None,
    city_consistent: bool | None,
    province_consistent: bool | None,
) -> str:
    location = f"{preferred_city}, {province or '未知省份'}"
    if city_consistent is False or province_consistent is False:
        parts = []
        if city_consistent is False:
            parts.append("城市与本地邮编库不一致")
        if province_consistent is False:
            parts.append("省份与本地邮编库不一致")
        return (
            f"本地邮编库命中 {postal_code} -> {location}，但{'、'.join(parts)}。"
            "系统应优先使用本地邮编库城市/省份做 Zone 匹配，地图仅供人工目视确认。"
        )
    if city_consistent is None and province_consistent is None:
        return (
            f"本地邮编库命中 {postal_code} -> {location}。"
            "原始输入未明确城市/省份时，可用该记录补齐地址字段。"
        )
    return (
        f"本地邮编库命中 {postal_code} -> {location}，"
        "城市/省份与解析结果一致。地图仅供人工目视确认，不参与金额计算。"
    )
