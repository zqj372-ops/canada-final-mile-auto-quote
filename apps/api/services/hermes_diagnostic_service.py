from __future__ import annotations

import ast
import json
import logging
import os
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask
from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
from apps.api.db.repositories.hermes_diagnostic_repository import (
    HermesDiagnosticRepository,
    hermes_diagnostic_to_dict,
)
from apps.api.db.repositories.zone_repository import ZoneRepository
from packages.ai_assistant.model_client import AIMessage, OpenAICompatibleClient, config_from_record
from packages.address_normalizer import extract_fsa, normalize_city, normalize_province
from packages.quote_engine.zone_lookup import ORIGIN_BY_PROVINCE
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


logger = logging.getLogger(__name__)


class HermesDiagnosticSuggestionPayload(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    suggested_action: Literal[
        "no_action",
        "manual_review",
        "learning_candidate",
        "suggest_zone_matrix",
    ] = "no_action"
    can_auto_correct: Literal[False] = False
    confidence: int = Field(default=0, ge=0, le=100)
    reason_zh: str = Field(min_length=1, max_length=1000)
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
            "role": "Hermes Agent only diagnoses and suggests. It cannot execute a correction or change any price.",
            "execution_mode": "advisory_only",
            "can_change_quote": False,
            "can_change_price": False,
            "can_change_zone_matrix": False,
            "allowed_outputs": [
                "suggested_action",
                "reason_zh",
                "suggested_origin",
                "suggested_zone",
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


def run_hermes_diagnostic(
    db: Session,
    diagnostic_id: int,
) -> dict[str, object]:
    diagnostic_repository = HermesDiagnosticRepository(db)
    diagnostic = diagnostic_repository.get(diagnostic_id)
    if diagnostic is None:
        raise HTTPException(status_code=404, detail="Hermes diagnostic package not found.")

    config_repository = AIModelConfigRepository(db)
    config_record = config_repository.get_agent_config("hermes")
    if config_record is None:
        raise HTTPException(status_code=400, detail="Hermes Agent has no enabled model configuration.")

    client = OpenAICompatibleClient(
        config_from_record(
            config_record,
            api_key=config_repository.decrypt_api_key(config_record),
        )
    )
    response = client.complete(
        _build_hermes_messages(diagnostic.diagnostic_package_json)
    )
    if response.error:
        return fail_hermes_diagnostic(db, diagnostic_id, error=response.error)

    try:
        payload = _validate_hermes_suggestion(response.content)
    except (ValueError, ValidationError) as first_error:
        repair = client.complete(
            [
                *_build_hermes_messages(diagnostic.diagnostic_package_json),
                AIMessage(role="assistant", content=response.content[:6000]),
                AIMessage(
                    role="user",
                    content=(
                        "上次输出未通过 JSON/schema 校验："
                        f"{_compact_validation_error(first_error)}。"
                        "重新输出一个完整 JSON 对象；不要输出思考过程、Markdown 或任何额外文字。"
                        "can_auto_correct 必须是 false，也不能包含任何价格修改字段。"
                    ),
                ),
            ]
        )
        if repair.error:
            return fail_hermes_diagnostic(db, diagnostic_id, error=repair.error)
        try:
            payload = _validate_hermes_suggestion(repair.content)
        except (ValueError, ValidationError) as repair_error:
            logger.warning(
                "Hermes returned invalid structured suggestions twice.",
                extra={
                    "diagnostic_id": diagnostic_id,
                    "first_error": _compact_validation_error(first_error),
                    "repair_error": _compact_validation_error(repair_error),
                },
            )
            return fail_hermes_diagnostic(
                db,
                diagnostic_id,
                error="Hermes 模型连续两次未返回可验证的结构化建议；系统未采纳任何模型输出。",
            )
    except Exception as exc:
        return fail_hermes_diagnostic(
            db,
            diagnostic_id,
            error=f"Hermes model response validation failed: {exc.__class__.__name__}",
        )
    return submit_hermes_diagnostic_suggestion(db, diagnostic_id, payload)


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


_HERMES_DIAGNOSTIC_SYSTEM_PROMPT = """你是加拿大尾程报价系统内置的 Hermes 诊断 Agent。
你的运行模式永远是 advisory_only：只能解释诊断包并提出建议，不能执行建议。
你不能改价、建议新价格、编造价格、编造 Zone，也不能修改报价结果或更新任何表。
价格和 Zone 必须来自 diagnostic_package 中已有的后端证据。证据不足时，必须建议人工复核。
can_auto_correct 必须为 false。只返回符合 output_schema 的一个 JSON 对象，不要返回思考过程或 Markdown。
""".strip()


def _build_hermes_messages(diagnostic_package: dict[str, object]) -> list[AIMessage]:
    return [
        AIMessage(role="system", content=_HERMES_DIAGNOSTIC_SYSTEM_PROMPT),
        AIMessage(
            role="user",
            content=json.dumps(
                {
                    "task": "diagnose_quote_and_return_advisory_suggestion_only",
                    "diagnostic_package": diagnostic_package,
                    "output_schema": HermesDiagnosticSuggestionPayload.model_json_schema(),
                    "required_invariants": {
                        "can_auto_correct": False,
                        "must_not_change_quote": True,
                        "must_not_change_price": True,
                        "must_not_change_zone_matrix": True,
                    },
                },
                ensure_ascii=False,
            ),
        ),
    ]


def _validate_hermes_suggestion(content: str) -> HermesDiagnosticSuggestionPayload:
    candidates = _parse_json_objects(content)
    if not candidates:
        raise ValueError("Hermes output did not contain a complete JSON object.")

    last_error: ValidationError | None = None
    for candidate in reversed(candidates):
        try:
            return HermesDiagnosticSuggestionPayload.model_validate(
                _sanitize_model_suggestion(candidate)
            )
        except ValidationError as exc:
            last_error = exc
    if last_error is not None:
        raise last_error
    raise ValueError("Hermes output did not contain a valid suggestion.")


def _sanitize_model_suggestion(data: dict[str, Any]) -> dict[str, Any]:
    allowed_fields = set(HermesDiagnosticSuggestionPayload.model_fields)
    sanitized = {key: value for key, value in data.items() if key in allowed_fields}

    if "reason_zh" not in sanitized:
        sanitized["reason_zh"] = data.get("reason") or data.get("explanation")
    sanitized["can_auto_correct"] = False
    sanitized["confidence"] = _bounded_int(sanitized.get("confidence"), default=0)

    for field in ("recommend_manual_review", "recommend_learning_candidate"):
        sanitized[field] = _coerce_bool(sanitized.get(field), default=field == "recommend_manual_review")

    for field in ("evidence_ids", "notes"):
        value = sanitized.get(field)
        if value is None:
            sanitized[field] = []
        elif isinstance(value, str):
            sanitized[field] = [value]
        elif not isinstance(value, list):
            sanitized[field] = []

    action_aliases = {
        "suggest_manual_review": "manual_review",
        "recommend_manual_review": "manual_review",
        "recommend_learning_candidate": "learning_candidate",
        "suggest_learning_candidate": "learning_candidate",
    }
    action = str(sanitized.get("suggested_action") or "no_action").strip().lower()
    sanitized["suggested_action"] = action_aliases.get(action, action)
    return sanitized


def _parse_json_objects(content: str) -> list[dict[str, Any]]:
    text = content.lstrip("\ufeff").strip()
    if not text:
        return []

    parsed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in _balanced_object_candidates(text):
        compact = candidate.strip()
        if not compact or compact in seen:
            continue
        seen.add(compact)
        value = _load_jsonish_object(compact)
        if isinstance(value, dict):
            parsed.append(value)
    return parsed


def _balanced_object_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    start: int | None = None
    depth = 0
    in_string = False
    escaped = False

    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = index
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidates.append(text[start : index + 1])
                start = None
    return candidates


def _load_jsonish_object(candidate: str) -> dict[str, Any] | None:
    attempts = [
        candidate,
        re.sub(r",\s*([}\]])", r"\1", candidate),
    ]
    for attempt in attempts:
        try:
            value = json.loads(attempt)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value

    try:
        value = ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _compact_validation_error(error: Exception) -> str:
    return " ".join(str(error).split())[:1000]


def _bounded_int(value: object, *, default: int) -> int:
    if isinstance(value, str):
        match = re.search(r"-?\d+", value)
        value = match.group(0) if match else None
    try:
        return max(0, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _coerce_bool(value: object, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y", "是", "建议"}:
            return True
        if lowered in {"false", "0", "no", "n", "否", "不建议"}:
            return False
    if isinstance(value, (int, float)):
        return bool(value)
    return default


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
