from __future__ import annotations

import json
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import (
    CityAlias,
    PostalCodeCityLookup,
    PostalZoneOverride,
    QuoteReleaseManifest,
    ZoneLookupRule,
    ZonePriceMatrix,
)
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository


SCHEMA_VERSION = "source-status.v1"
SYSTEM = "ai_quote"
CONTRACT_VERSION = "quote-zone.v1"
SUPPORTED_OPERATIONS = ["quote.zone_preview"]
_EXPECTED_RELEASE_ENV = "QUOTE_RELEASE_ID"
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
    actual_snapshot_hash = source_data_hash(db) if db is not None else None
    manifest = _active_manifest(db) if db is not None else None
    test_data = _source_data_is_test_data(db) if db is not None else False
    if manifest is None:
        reasons.append("release_manifest_missing")
    elif manifest.test_data:
        test_data = True
    if test_data:
        reasons.append("test_data_not_authoritative")

    manifest_values: dict[str, str | None] = {}
    published_at: str | None = None
    if manifest is not None:
        for field in ("release_id", "service_version", "rule_version", "data_version"):
            manifest_values[field] = _manifest_text(getattr(manifest, field), field, reasons)
        published_at = _manifest_published_at(manifest.published_at, reasons)

    expected_release_id = _env(_EXPECTED_RELEASE_ENV)
    if (
        expected_release_id
        and manifest_values.get("release_id")
        and manifest_values["release_id"] != expected_release_id
    ):
        reasons.append("deployment_config_mismatch:QUOTE_RELEASE_ID")
    if manifest is not None and actual_snapshot_hash is not None:
        if _normalize_hash(manifest.snapshot_hash) != actual_snapshot_hash:
            reasons.append("release_manifest_snapshot_mismatch")
    if manifest is not None:
        if manifest.valid_to < manifest.valid_from:
            reasons.append("release_manifest_invalid:effective_window")
        today = date.today()
        if manifest.valid_from > today:
            reasons.append("effective_window_not_active:before_valid_from")
        if manifest.valid_to < today:
            reasons.append("effective_window_not_active:after_valid_to")
    if actual_snapshot_hash is None:
        reasons.append("source_data_unavailable")

    return SourceStatus(
        ready=not reasons,
        test_data=bool(test_data),
        service_version=manifest_values.get("service_version"),
        release_id=manifest_values.get("release_id"),
        release_hash=(
            actual_snapshot_hash
            if manifest is not None
            and actual_snapshot_hash is not None
            and _normalize_hash(manifest.snapshot_hash) == actual_snapshot_hash
            else None
        ),
        snapshot_hash=actual_snapshot_hash,
        rule_version=manifest_values.get("rule_version"),
        data_version=manifest_values.get("data_version"),
        published_at=published_at,
        reasons=reasons,
        supported_operations=list(SUPPORTED_OPERATIONS),
        valid_from=manifest.valid_from.isoformat() if manifest is not None else None,
        valid_to=manifest.valid_to.isoformat() if manifest is not None else None,
    )


def source_data_hash(db: Session) -> str:
    db.expire_all()
    postal_city_lookups = db.scalars(
        select(PostalCodeCityLookup)
        .order_by(PostalCodeCityLookup.postal_code)
        .execution_options(populate_existing=True)
    ).all()
    postal_overrides = db.scalars(
        select(PostalZoneOverride)
        .where(PostalZoneOverride.active.is_(True))
        .order_by(PostalZoneOverride.postal_code, PostalZoneOverride.id)
        .execution_options(populate_existing=True)
    ).all()
    city_aliases = db.scalars(
        select(CityAlias)
        .where(CityAlias.active.is_(True))
        .order_by(CityAlias.province, CityAlias.alias_city, CityAlias.id)
        .execution_options(populate_existing=True)
    ).all()
    rules = db.scalars(
        select(ZoneLookupRule)
        .where(ZoneLookupRule.active.is_(True))
        .order_by(
            ZoneLookupRule.postal_prefix,
            ZoneLookupRule.city,
            ZoneLookupRule.province,
            ZoneLookupRule.origin,
            ZoneLookupRule.zone,
            ZoneLookupRule.priority,
            ZoneLookupRule.id,
        )
        .execution_options(populate_existing=True)
    ).all()
    prices = db.scalars(
        select(ZonePriceMatrix)
        .order_by(ZonePriceMatrix.origin, ZonePriceMatrix.zone, ZonePriceMatrix.billing_pallets, ZonePriceMatrix.id)
        .execution_options(populate_existing=True)
    ).all()
    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    payload = {
        "postal_code_city_lookup": [
            {
                "postal_code": record.postal_code,
                "preferred_city": record.preferred_city,
                "province": record.province,
                "fsa": record.fsa,
                "official_city": record.official_city,
                "municipality": record.municipality,
                "latitude": _canonical_decimal(record.latitude),
                "longitude": _canonical_decimal(record.longitude),
                "source": record.source,
            }
            for record in postal_city_lookups
        ],
        "postal_zone_overrides": [
            {
                "id": record.id,
                "postal_code": record.postal_code,
                "postal_prefix": record.postal_prefix,
                "province": record.province,
                "canonical_city": record.canonical_city,
                "origin": record.origin,
                "zone": record.zone,
                "confidence": record.confidence,
                "active": record.active,
                "source": record.source,
                "note": record.note,
            }
            for record in postal_overrides
        ],
        "city_aliases": [
            {
                "id": record.id,
                "province": record.province,
                "alias_city": record.alias_city,
                "canonical_city": record.canonical_city,
                "alias_type": record.alias_type,
                "active": record.active,
                "source": record.source,
                "note": record.note,
            }
            for record in city_aliases
        ],
        "zone_lookup_rules": [
            {
                "id": record.id,
                "postal_prefix": record.postal_prefix,
                "city": record.city,
                "province": record.province,
                "origin": record.origin,
                "zone": record.zone,
                "canonical_city": record.canonical_city,
                "priority": record.priority,
                "active": record.active,
                "match_level": record.match_level,
                "note": record.note,
            }
            for record in rules
        ],
        "zone_price_matrix": [
            {
                "id": record.id,
                "origin": record.origin,
                "zone": record.zone,
                "billing_pallets": record.billing_pallets,
                "base_price_usd": _canonical_decimal(record.base_price_usd),
                "source": record.source,
                "last_updated": record.last_updated,
            }
            for record in prices
        ],
        "zone_pricing_config": pricing_config.model_dump(mode="json"),
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"sha256:{sha256(encoded).hexdigest()}"


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


def _active_manifest(db: Session) -> QuoteReleaseManifest | None:
    manifests = db.scalars(
        select(QuoteReleaseManifest)
        .where(QuoteReleaseManifest.active.is_(True))
        .order_by(QuoteReleaseManifest.updated_at.desc(), QuoteReleaseManifest.id.desc())
    ).all()
    if len(manifests) != 1:
        return None
    return manifests[0]


def _source_data_is_test_data(db: Session) -> bool:
    values = [
        *db.scalars(select(PostalCodeCityLookup.source)).all(),
        *db.scalars(select(PostalZoneOverride.source).where(PostalZoneOverride.active.is_(True))).all(),
        *db.scalars(select(CityAlias.source).where(CityAlias.active.is_(True))).all(),
        *db.scalars(select(ZonePriceMatrix.source)).all(),
    ]
    return any(isinstance(value, str) and value.strip().lower() in _TEST_DATA_MARKERS for value in values)


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
