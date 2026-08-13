from __future__ import annotations

import os
import re
import json
from datetime import date, datetime
from decimal import Decimal
from hashlib import sha256
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import ZoneLookupRule, ZonePriceMatrix


SCHEMA_VERSION = "source-status.v1"
SYSTEM = "ai_quote"
CONTRACT_VERSION = "quote-zone.v1"
SUPPORTED_OPERATIONS = ["quote.zone_preview"]
_REQUIRED_ENV = (
    "QUOTE_SERVICE_VERSION",
    "QUOTE_RELEASE_ID",
    "QUOTE_RELEASE_HASH",
    "QUOTE_RULE_VERSION",
    "QUOTE_DATA_VERSION",
    "QUOTE_PUBLISHED_AT",
    "QUOTE_VALID_FROM",
    "QUOTE_VALID_TO",
    "QUOTE_TEST_DATA",
)
_PLACEHOLDERS = {"latest", "unknown", "none", "null"}
_HASH_PATTERN = re.compile(r"^(?:sha256:)?[0-9a-f]{7,64}$", re.IGNORECASE)


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
    values = {name: _env(name) for name in _REQUIRED_ENV}
    reasons: list[str] = []
    actual_snapshot_hash = source_data_hash(db) if db is not None else None
    for name in _REQUIRED_ENV:
        if values[name] is None:
            reasons.append(f"deployment_config_missing:{name}")

    for name in ("QUOTE_SERVICE_VERSION", "QUOTE_RELEASE_ID", "QUOTE_RULE_VERSION", "QUOTE_DATA_VERSION"):
        value = values[name]
        if value is not None and value.lower() in _PLACEHOLDERS:
            reasons.append(f"deployment_config_invalid:{name}")

    release_hash = values["QUOTE_RELEASE_HASH"]
    if release_hash is not None and (
        release_hash.lower() in _PLACEHOLDERS or not _HASH_PATTERN.fullmatch(release_hash)
    ):
        reasons.append("deployment_config_invalid:QUOTE_RELEASE_HASH")

    published_at = values["QUOTE_PUBLISHED_AT"]
    if published_at is not None and not _parse_datetime(published_at):
        reasons.append("deployment_config_invalid:QUOTE_PUBLISHED_AT")

    valid_from = values["QUOTE_VALID_FROM"]
    valid_from_date = _parse_date(valid_from) if valid_from is not None else None
    if valid_from is not None and valid_from_date is None:
        reasons.append("deployment_config_invalid:QUOTE_VALID_FROM")

    valid_to = values["QUOTE_VALID_TO"]
    valid_to_date = _parse_date(valid_to) if valid_to is not None else None
    if valid_to is not None and valid_to_date is None:
        reasons.append("deployment_config_invalid:QUOTE_VALID_TO")
    if valid_from_date and valid_to_date and valid_to_date < valid_from_date:
        reasons.append("deployment_config_invalid:effective_window")
    today = date.today()
    if valid_from_date and valid_from_date > today:
        reasons.append("effective_window_not_active:before_valid_from")
    if valid_to_date and valid_to_date < today:
        reasons.append("effective_window_not_active:after_valid_to")

    test_data = _parse_bool(values["QUOTE_TEST_DATA"])
    if values["QUOTE_TEST_DATA"] is not None and test_data is None:
        reasons.append("deployment_config_invalid:QUOTE_TEST_DATA")
        test_data = False
    if test_data:
        reasons.append("test_data_not_authoritative")
    if actual_snapshot_hash is None:
        reasons.append("source_data_unavailable")
    elif release_hash is not None and _normalize_hash(release_hash) != actual_snapshot_hash:
        reasons.append("deployment_config_mismatch:QUOTE_RELEASE_HASH")

    return SourceStatus(
        ready=not reasons,
        test_data=bool(test_data),
        service_version=values["QUOTE_SERVICE_VERSION"],
        release_id=values["QUOTE_RELEASE_ID"],
        release_hash=actual_snapshot_hash if release_hash and _normalize_hash(release_hash) == actual_snapshot_hash else None,
        snapshot_hash=actual_snapshot_hash,
        rule_version=values["QUOTE_RULE_VERSION"],
        data_version=values["QUOTE_DATA_VERSION"],
        published_at=published_at,
        reasons=reasons,
        supported_operations=list(SUPPORTED_OPERATIONS),
        valid_from=valid_from,
        valid_to=valid_to,
    )


def source_data_hash(db: Session) -> str:
    db.expire_all()
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
    payload = {
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


def _parse_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    if value.lower() in {"1", "true", "yes", "on"}:
        return True
    if value.lower() in {"0", "false", "no", "off"}:
        return False
    return None


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _canonical_decimal(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _normalize_hash(value: str) -> str:
    normalized = value.lower()
    return normalized if normalized.startswith("sha256:") else f"sha256:{normalized}"
