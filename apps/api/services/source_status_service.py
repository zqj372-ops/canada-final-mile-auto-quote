from __future__ import annotations

import json
import os
from collections.abc import Mapping
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from importlib import metadata
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from apps.api.db.models import (
    CityAlias,
    PostalCodeCityLookup,
    PostalZoneOverride,
    QuoteReleaseManifest,
    QuoteRuleConfig,
    QuoteSourceGeneration,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository


SCHEMA_VERSION = "source-status.v1"
SYSTEM = "ai_quote"
CONTRACT_VERSION = "quote-zone.v1"
SUPPORTED_OPERATIONS = ["quote.zone_preview"]
_EXPECTED_RELEASE_ENV = "QUOTE_RELEASE_ID"
_PACKAGE_NAME = "canada-final-mile-auto-quote"
_TEST_DATA_MARKERS = {"demo", "fixture", "mock", "sample", "test", "test_data"}
_MANIFEST_PLACEHOLDERS = {
    "latest",
    "unknown",
    "none",
    "null",
    "pending",
    "pending_review",
    "draft",
    "unset",
    "tbd",
    "n/a",
    "na",
}


class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["source-status.v1"] = SCHEMA_VERSION
    system: Literal["ai_quote"] = SYSTEM
    ready: bool
    test_data: bool
    service_version: str | None
    contract_version: Literal["quote-zone.v1"] = CONTRACT_VERSION
    release_id: str | None
    release_hash: str | None
    snapshot_hash: str | None
    rule_version: str | None
    data_version: str | None
    published_at: str | None
    reasons: list[str]
    supported_operations: list[str]
    valid_from: str | None = None
    valid_to: str | None = None


def get_source_status(db: Session | None = None) -> SourceStatus:
    reasons: list[str] = []
    manifest, source_generation = _active_release_evidence(db) if db is not None else (None, None)
    test_data = bool(manifest.test_data) if manifest is not None else False
    if manifest is None:
        reasons.append("release_manifest_missing")
    if test_data:
        reasons.append("test_data_not_authoritative")

    manifest_values: dict[str, str | None] = {}
    published_at: str | None = None
    if manifest is not None:
        for field in ("release_id", "service_version", "rule_version", "data_version"):
            manifest_values[field] = _manifest_text(getattr(manifest, field), field, reasons)
        published_at = _manifest_published_at(manifest.published_at, reasons)

    expected_release_id = _env(_EXPECTED_RELEASE_ENV)
    if not expected_release_id:
        reasons.append("deployment_config_missing:QUOTE_RELEASE_ID")
    elif manifest_values.get("release_id") != expected_release_id:
        reasons.append("deployment_config_mismatch:QUOTE_RELEASE_ID")
    installed_service_version = _installed_service_version()
    if installed_service_version is None:
        reasons.append("service_version_metadata_unavailable")
    elif manifest_values.get("service_version") != installed_service_version:
        reasons.append("release_manifest_service_version_mismatch")
    if manifest is not None:
        if source_generation is None:
            reasons.append("source_generation_unavailable")
        elif manifest.source_generation != source_generation.generation:
            reasons.append("release_manifest_source_generation_mismatch")
        if manifest.valid_to < manifest.valid_from:
            reasons.append("release_manifest_invalid:effective_window")
        today = date.today()
        if manifest.valid_from > today:
            reasons.append("effective_window_not_active:before_valid_from")
        if manifest.valid_to < today:
            reasons.append("effective_window_not_active:after_valid_to")
    snapshot_hash = _normalize_hash(manifest.snapshot_hash) if manifest is not None else None
    evidence_bound = (
        manifest is not None
        and source_generation is not None
        and manifest.source_generation == source_generation.generation
    )

    return SourceStatus(
        ready=not reasons,
        test_data=bool(test_data),
        service_version=manifest_values.get("service_version"),
        release_id=manifest_values.get("release_id"),
        release_hash=snapshot_hash if evidence_bound else None,
        snapshot_hash=snapshot_hash,
        rule_version=manifest_values.get("rule_version"),
        data_version=manifest_values.get("data_version"),
        published_at=published_at,
        reasons=reasons,
        supported_operations=list(SUPPORTED_OPERATIONS),
        valid_from=manifest.valid_from.isoformat() if manifest is not None else None,
        valid_to=manifest.valid_to.isoformat() if manifest is not None else None,
    )


def source_data_hash(db: Session) -> str:
    digest = sha256()
    _hash_table(
        digest,
        db,
        "postal_code_city_lookup",
        select(
            PostalCodeCityLookup.postal_code,
            PostalCodeCityLookup.preferred_city,
            PostalCodeCityLookup.province,
            PostalCodeCityLookup.fsa,
            PostalCodeCityLookup.official_city,
            PostalCodeCityLookup.municipality,
            PostalCodeCityLookup.latitude,
            PostalCodeCityLookup.longitude,
            PostalCodeCityLookup.source,
        ).order_by(PostalCodeCityLookup.postal_code),
    )
    _hash_table(
        digest,
        db,
        "postal_zone_overrides",
        select(
            PostalZoneOverride.id,
            PostalZoneOverride.postal_code,
            PostalZoneOverride.postal_prefix,
            PostalZoneOverride.province,
            PostalZoneOverride.canonical_city,
            PostalZoneOverride.origin,
            PostalZoneOverride.zone,
            PostalZoneOverride.confidence,
            PostalZoneOverride.active,
            PostalZoneOverride.source,
            PostalZoneOverride.note,
        )
        .where(PostalZoneOverride.active.is_(True))
        .order_by(PostalZoneOverride.postal_code, PostalZoneOverride.id),
    )
    _hash_table(
        digest,
        db,
        "city_aliases",
        select(
            CityAlias.id,
            CityAlias.province,
            CityAlias.alias_city,
            CityAlias.canonical_city,
            CityAlias.alias_type,
            CityAlias.active,
            CityAlias.source,
            CityAlias.note,
        )
        .where(CityAlias.active.is_(True))
        .order_by(CityAlias.province, CityAlias.alias_city, CityAlias.id),
    )
    _hash_table(
        digest,
        db,
        "zone_lookup_rules",
        select(
            ZoneLookupRule.id,
            ZoneLookupRule.postal_prefix,
            ZoneLookupRule.city,
            ZoneLookupRule.province,
            ZoneLookupRule.origin,
            ZoneLookupRule.zone,
            ZoneLookupRule.canonical_city,
            ZoneLookupRule.priority,
            ZoneLookupRule.active,
            ZoneLookupRule.match_level,
            ZoneLookupRule.note,
        )
        .where(ZoneLookupRule.active.is_(True))
        .order_by(
            ZoneLookupRule.postal_prefix,
            ZoneLookupRule.city,
            ZoneLookupRule.province,
            ZoneLookupRule.origin,
            ZoneLookupRule.zone,
            ZoneLookupRule.priority,
            ZoneLookupRule.id,
        ),
    )
    _hash_table(
        digest,
        db,
        "zone_price_matrix",
        select(
            ZonePriceMatrix.id,
            ZonePriceMatrix.origin,
            ZonePriceMatrix.zone,
            ZonePriceMatrix.billing_pallets,
            ZonePriceMatrix.base_price_usd,
            ZonePriceMatrix.source,
            ZonePriceMatrix.last_updated,
        ).order_by(ZonePriceMatrix.origin, ZonePriceMatrix.zone, ZonePriceMatrix.billing_pallets, ZonePriceMatrix.id),
    )
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    _hash_value(digest, "zone_pricing_config", pricing_config.model_dump(mode="json"))
    return f"sha256:{digest.hexdigest()}"


def _hash_table(digest, db: Session, table_name: str, statement) -> None:
    fields = tuple(column.key for column in statement.selected_columns)
    _hash_value(digest, "table", {"name": table_name, "fields": fields})
    result = db.execute(statement.execution_options(stream_results=True, yield_per=5000))
    for row in result:
        _hash_value(digest, "row", dict(zip(fields, row, strict=True)))


def _hash_value(digest, kind: str, value: object) -> None:
    encoded = json.dumps(
        {"kind": kind, "value": _canonical_json(value)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest.update(len(encoded).to_bytes(8, "big"))
    digest.update(encoded)


def _canonical_json(value: object) -> object:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_json(item)
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_json(item) for item in value]
    if value is None or isinstance(value, (bool, float, int, str)):
        return value
    return str(value)


def source_status_version_key(status: SourceStatus) -> tuple[object, ...]:
    return (
        status.ready,
        status.test_data,
        status.service_version,
        status.release_id,
        status.release_hash,
        status.snapshot_hash,
        status.rule_version,
        status.data_version,
        status.published_at,
        status.valid_from,
        status.valid_to,
    )


def quote_version(status: SourceStatus) -> str | None:
    if not status.ready or not status.release_id or not status.rule_version or not status.data_version:
        return None
    return f"{status.release_id}:{status.rule_version}:{status.data_version}"


def _env(name: str) -> str | None:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else None


def _installed_service_version() -> str | None:
    try:
        value = metadata.version(_PACKAGE_NAME).strip()
    except (metadata.PackageNotFoundError, ValueError):
        return None
    return value or None


def _active_manifest(db: Session) -> QuoteReleaseManifest | None:
    return _active_release_evidence(db)[0]


def _active_release_evidence(
    db: Session,
) -> tuple[QuoteReleaseManifest | None, QuoteSourceGeneration | None]:
    source_generation = db.scalar(
        select(QuoteSourceGeneration)
        .where(QuoteSourceGeneration.id == 1)
    )
    manifests = db.scalars(
        select(QuoteReleaseManifest)
        .where(QuoteReleaseManifest.active.is_(True))
        .order_by(QuoteReleaseManifest.updated_at.desc(), QuoteReleaseManifest.id.desc())
        .limit(2)
    ).all()
    return (manifests[0] if len(manifests) == 1 else None, source_generation)


def _source_data_is_test_data(db: Session) -> bool:
    marker_columns = (
        (PostalCodeCityLookup.source, ()),
        (PostalZoneOverride.source, (PostalZoneOverride.active.is_(True),)),
        (PostalZoneOverride.note, (PostalZoneOverride.active.is_(True),)),
        (CityAlias.source, (CityAlias.active.is_(True),)),
        (CityAlias.note, (CityAlias.active.is_(True),)),
        (ZoneLookupRule.match_level, (ZoneLookupRule.active.is_(True),)),
        (ZoneLookupRule.note, (ZoneLookupRule.active.is_(True),)),
        (ZonePriceMatrix.source, ()),
        (QuoteRuleConfig.value, ()),
        (QuoteRuleConfig.description, ()),
    )
    markers = tuple(sorted(_TEST_DATA_MARKERS))
    return any(
        db.scalar(
            select(column)
            .where(func.lower(func.trim(column)).in_(markers), *conditions)
            .limit(1)
        )
        is not None
        for column, conditions in marker_columns
    )


def _manifest_text(value: object, field: str, reasons: list[str]) -> str | None:
    normalized = value.strip() if isinstance(value, str) else ""
    if not normalized or normalized.lower() in _MANIFEST_PLACEHOLDERS:
        reasons.append(f"release_manifest_invalid:{field}")
        return None
    return normalized


def _manifest_published_at(value: object, reasons: list[str]) -> str | None:
    try:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        else:
            raise ValueError
    except (TypeError, ValueError):
        reasons.append("release_manifest_invalid:published_at")
        return None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        reasons.append("release_manifest_invalid:published_at")
        return None
    normalized = parsed.astimezone(timezone.utc)
    if normalized > datetime.now(timezone.utc):
        reasons.append("release_manifest_invalid:published_at")
        return None
    return normalized.isoformat()


def _canonical_decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _normalize_hash(value: str) -> str:
    normalized = value.lower()
    return normalized if normalized.startswith("sha256:") else f"sha256:{normalized}"
