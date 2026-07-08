from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask
from apps.api.db.repositories.hermes_diagnostic_repository import (
    HermesDiagnosticRepository,
    hermes_diagnostic_to_dict,
)
from apps.api.db.repositories.zone_repository import ZoneRepository
from packages.address_normalizer import extract_fsa, normalize_city, normalize_province
from packages.quote_engine.zone_lookup import ORIGIN_BY_PROVINCE
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


logger = logging.getLogger(__name__)


class HermesDiagnosticSuggestionPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="allow")

    suggested_action: str = Field(default="no_action")
    can_auto_correct: bool = False
    confidence: int = Field(default=0, ge=0, le=100)
    reason_zh: str
    suggested_origin: str | None = None
    suggested_zone: int | None = None
    missing_table: str | None = None
    recommend_manual_review: bool = True
    recommend_learning_candidate: bool = False
    evidence_ids: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


def enqueue_quote_diagnostic(
    db: Session,
    request: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    *,
    raw_input: str | None = None,
    extraction: dict[str, object] | None = None,
    source: str = "zone_quote",
) -> dict[str, object] | None:
    try:
        package = build_quote_diagnostic_package(
            db,
            request,
            result,
            raw_input=raw_input,
            extraction=extraction,
            source=source,
        )
        record = HermesDiagnosticRepository(db).create(
            quote_id=result.quote_id,
            quote_status="manual_required" if result.manual_review_required else "quoted",
            source_type=result.source_type.value if hasattr(result.source_type, "value") else str(result.source_type),
            diagnostic_package_json=package,
        )
        return hermes_diagnostic_to_dict(record)
    except Exception:
        logger.exception("Failed to enqueue Hermes diagnostic package.", extra={"quote_id": result.quote_id})
        db.rollback()
        return None


def build_quote_diagnostic_package(
    db: Session,
    request: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    *,
    raw_input: str | None = None,
    extraction: dict[str, object] | None = None,
    source: str = "zone_quote",
) -> dict[str, object]:
    repository = ZoneRepository(db)
    postal_prefix = result.postal_prefix or extract_fsa(request.postal_code)
    province = result.province or request.province
    city = result.city or request.city
    expected_origin = ORIGIN_BY_PROVINCE.get(normalize_province(province) or "")

    return {
        "schema_version": "2026-07-08.hermes-diagnostic.v1",
        "source": source,
        "quote_id": result.quote_id,
        "quote_status": "manual_required" if result.manual_review_required else "quoted",
        "raw_input": raw_input,
        "parsed_result": extraction or {},
        "quote_request": request.model_dump(mode="json"),
        "quote_result": result.model_dump(mode="json"),
        "address": {
            "postal_code": request.postal_code,
            "postal_prefix": postal_prefix,
            "city": city,
            "province": province,
            "expected_origin_by_province": expected_origin,
            "preferred_city": result.preferred_city,
        },
        "zone_hit": {
            "source_type": result.source_type.value if hasattr(result.source_type, "value") else str(result.source_type),
            "matched_by": result.matched_by,
            "matched_rule": result.matched_rule,
            "candidate_count": result.candidate_count,
            "origin": result.origin,
            "zone": result.zone,
            "match_trace": result.match_trace,
        },
        "price_matrix": _price_matrix_context(repository, result),
        "failure": {
            "manual_review_required": result.manual_review_required,
            "reason": result.matched_rule if result.manual_review_required else None,
            "risk_tags": result.risk_tags,
            "internal_note": result.internal_note,
        },
        "neighboring_fsa": _neighboring_fsa_context(repository, postal_prefix, province, result.billing_pallets),
        "historical_manual_confirmations": _historical_manual_confirmations(
            db,
            city=city,
            province=province,
            postal_prefix=postal_prefix,
            billing_pallets=result.billing_pallets,
        ),
        "private_reference_context": _private_reference_context(
            postal_code=request.postal_code,
            city=city,
            province=province,
            cbm=request.cbm,
            weight_kg=request.weight_kg,
        ),
        "agent_contract": {
            "role": "Hermes Agent only diagnoses. It must not change quote_result or zone_price_matrix.",
            "allowed_outputs": [
                "can_auto_correct",
                "why_this_zone",
                "missing_table",
                "recommend_manual_review",
                "recommend_learning_candidate",
            ],
            "learning_rule_policy": "Only a resolved manual task can create a learning candidate; approval is required before reuse.",
        },
    }


def list_hermes_diagnostics(
    db: Session,
    *,
    status: str | None = None,
    quote_id: str | None = None,
    limit: int = 50,
) -> list[dict[str, object]]:
    records = HermesDiagnosticRepository(db).list_records(status=status, quote_id=quote_id, limit=limit)
    return [hermes_diagnostic_to_dict(record) for record in records]


def get_hermes_diagnostic(db: Session, diagnostic_id: int) -> dict[str, object]:
    record = HermesDiagnosticRepository(db).get(diagnostic_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Hermes diagnostic package not found.")
    return hermes_diagnostic_to_dict(record)


def submit_hermes_diagnostic_suggestion(
    db: Session,
    diagnostic_id: int,
    payload: HermesDiagnosticSuggestionPayload,
) -> dict[str, object]:
    suggestion = payload.model_dump(mode="json")
    record = HermesDiagnosticRepository(db).save_suggestion(
        diagnostic_id,
        status="completed",
        suggestion=suggestion,
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Hermes diagnostic package not found.")
    return hermes_diagnostic_to_dict(record)


def fail_hermes_diagnostic(
    db: Session,
    diagnostic_id: int,
    *,
    error: str,
) -> dict[str, object]:
    record = HermesDiagnosticRepository(db).save_suggestion(
        diagnostic_id,
        status="failed",
        agent_error=error[:1000],
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Hermes diagnostic package not found.")
    return hermes_diagnostic_to_dict(record)


def _price_matrix_context(repository: ZoneRepository, result: ZoneQuoteResult) -> dict[str, object]:
    exact = None
    if result.origin and result.zone is not None and result.billing_pallets is not None:
        price = repository.get_zone_price(result.origin, result.zone, result.billing_pallets)
        if price:
            exact = {
                "origin": price.origin,
                "zone": price.zone,
                "billing_pallets": price.billing_pallets,
                "base_price_usd": f"{price.base_price_usd:.2f}",
                "source": price.source,
                "last_updated": price.last_updated,
            }
    return {
        "requested_origin": result.origin,
        "requested_zone": result.zone,
        "requested_billing_pallets": result.billing_pallets,
        "exact_price_found": exact is not None,
        "exact_price": exact,
        "base_price_usd": _decimal_string(result.base_price_usd),
        "fuel_usd": _decimal_string(result.fuel_usd),
        "total_price_usd": _decimal_string(result.total_price_usd),
    }


def _neighboring_fsa_context(
    repository: ZoneRepository,
    postal_prefix: str | None,
    province: str | None,
    billing_pallets: int | None,
) -> list[dict[str, object]]:
    if not postal_prefix or not province:
        return []
    rows = []
    for rule in repository.list_postal_family_zone_rules(postal_prefix, province)[:40]:
        price = repository.get_zone_price(rule.origin, rule.zone, billing_pallets) if billing_pallets else None
        rows.append(
            {
                "postal_prefix": rule.postal_prefix,
                "city": rule.city,
                "province": rule.province,
                "origin": rule.origin,
                "zone": rule.zone,
                "match_level": rule.match_level,
                "has_price_for_billing_pallets": price is not None,
                "base_price_usd": f"{price.base_price_usd:.2f}" if price else None,
                "note": rule.note,
            }
        )
    return rows[:18]


def _historical_manual_confirmations(
    db: Session,
    *,
    city: str | None,
    province: str | None,
    postal_prefix: str | None,
    billing_pallets: int | None,
) -> list[dict[str, object]]:
    normalized_city = normalize_city(city)
    normalized_province = normalize_province(province)
    prefix = (postal_prefix or "").upper()[:3]
    records = db.scalars(
        select(ManualQuoteTask)
        .where(ManualQuoteTask.status == "resolved", ManualQuoteTask.resolved_price_usd.is_not(None))
        .order_by(ManualQuoteTask.updated_at.desc(), ManualQuoteTask.id.desc())
        .limit(160)
    ).all()
    matches: list[dict[str, object]] = []
    for task in records:
        result_json = task.result_json or {}
        request_json = task.request_json or {}
        task_city = normalize_city(_string(result_json.get("city")) or _string(request_json.get("city")))
        task_province = normalize_province(_string(result_json.get("province")) or _string(request_json.get("province")))
        task_prefix = (_string(result_json.get("postal_prefix")) or extract_fsa(_string(request_json.get("postal_code")) or "") or "").upper()[:3]
        task_pallets = _int_value(result_json.get("billing_pallets"))
        if billing_pallets is not None and task_pallets not in {None, billing_pallets}:
            continue
        same_city = bool(task_city and normalized_city and task_city == normalized_city and task_province == normalized_province)
        same_prefix_family = bool(prefix and task_prefix and prefix[:2] == task_prefix[:2] and task_province == normalized_province)
        if not same_city and not same_prefix_family:
            continue
        matches.append(
            {
                "manual_task_id": task.id,
                "quote_id": task.quote_id,
                "postal_prefix": task_prefix or None,
                "city": task_city,
                "province": task_province,
                "origin": result_json.get("origin"),
                "zone": result_json.get("zone"),
                "billing_pallets": task_pallets,
                "resolved_price_usd": _decimal_string(task.resolved_price_usd),
                "resolved_note": task.resolved_note,
            }
        )
    return matches[:12]


def _private_reference_context(
    *,
    postal_code: str | None,
    city: str | None,
    province: str | None,
    cbm: Decimal,
    weight_kg: Decimal,
) -> dict[str, object]:
    pack_dir = _find_agent_pack_dir()
    if pack_dir is None:
        return {"available": False, "reason": "private address agent_pack not configured"}
    query_tool = pack_dir / "query_private_address_reference.py"
    command = [
        sys.executable,
        str(query_tool),
        "--cbm",
        str(cbm),
        "--weight-kg",
        str(weight_kg),
        "--limit",
        "3",
    ]
    if postal_code:
        command.extend(["--postal-code", postal_code])
    if city:
        command.extend(["--city", city])
    if province:
        command.extend(["--province", province])
    try:
        completed = subprocess.run(
            command,
            cwd=str(pack_dir),
            check=False,
            capture_output=True,
            text=True,
            timeout=2.5,
        )
    except Exception as exc:
        return {"available": False, "reason": f"agent_pack query failed: {exc.__class__.__name__}"}
    if completed.returncode != 0:
        return {"available": False, "reason": (completed.stderr or completed.stdout).strip()[:500]}
    try:
        data = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"available": False, "reason": "agent_pack returned non-JSON output"}
    if isinstance(data, dict):
        data.setdefault("available", True)
        return data
    return {"available": False, "reason": "agent_pack returned unsupported JSON shape"}


def _find_agent_pack_dir() -> Path | None:
    candidates = [
        os.getenv("PRIVATE_ADDRESS_AGENT_PACK_DIR"),
        "/app/reference/private_address_agent_pack",
        "/app/reference/agent_pack",
        "/home/opc/canada-final-mile-auto-quote/reference/private_address_agent_pack",
        "/Users/autumn/Desktop/agent_pack",
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate)
        if (path / "query_private_address_reference.py").is_file():
            return path
    return None


def _decimal_string(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{Decimal(value):.2f}"


def _int_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
