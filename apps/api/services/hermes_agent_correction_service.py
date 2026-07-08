from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.db.models import ManualQuoteTask, ZoneLookupRule
from apps.api.db.repositories.ai_model_config_repository import AIModelConfigRepository
from apps.api.db.repositories.zone_repository import ZoneRepository
from packages.ai_assistant.model_client import AIMessage, OpenAICompatibleClient, config_from_record
from packages.address_normalizer import extract_fsa, normalize_city, normalize_province
from packages.quote_engine.pricing import money
from packages.quote_engine.zone_config import ZonePricingConfig
from packages.quote_engine.zone_engine import build_zone_sales_note
from packages.quote_engine.zone_lookup import ORIGIN_BY_PROVINCE, normalize_origin, origin_label
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult, ZoneQuoteSourceType
from packages.quote_engine.zone_pricing import calculate_zone_price


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentDecision:
    action: str
    confidence: int
    reason_zh: str
    origin: str | None = None
    zone: int | None = None
    manual_task_id: int | None = None


def apply_hermes_agent_correction_if_available(
    db: Session,
    request: ZoneQuoteRequest,
    result: ZoneQuoteResult,
    *,
    pricing_config: ZonePricingConfig,
) -> ZoneQuoteResult:
    if not result.manual_review_required or result.billing_pallets is None:
        return result
    if "city_zone_prefix_family_low_support" in result.risk_tags:
        return result

    try:
        service = HermesAgentCorrectionService(db, pricing_config=pricing_config)
        return service.correct(request, result)
    except Exception:
        logger.exception("Hermes Agent correction failed.", extra={"quote_id": result.quote_id})
        db.rollback()
        return result


class HermesAgentCorrectionService:
    def __init__(self, db: Session, *, pricing_config: ZonePricingConfig):
        self.db = db
        self.pricing_config = pricing_config
        self.zone_repository = ZoneRepository(db)

    def correct(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> ZoneQuoteResult:
        evidence = self._build_evidence(request, result)
        if not evidence["zone_options"] and not evidence["resolved_manual_tasks"]:
            return result

        decision = self._ask_agent(request, result, evidence)
        if decision is None or decision.action == "no_action":
            return result
        if decision.action == "use_zone_matrix":
            return self._apply_zone_matrix_decision(request, result, decision, evidence)
        if decision.action == "use_resolved_manual_quote":
            return self._apply_manual_task_decision(request, result, decision, evidence)
        return result

    def _ask_agent(
        self,
        request: ZoneQuoteRequest,
        result: ZoneQuoteResult,
        evidence: dict[str, object],
    ) -> AgentDecision | None:
        config_repository = AIModelConfigRepository(self.db)
        config_record = config_repository.get_default_config(purpose="general")
        if config_record is None:
            return None

        client = OpenAICompatibleClient(
            config_from_record(config_record, api_key=config_repository.decrypt_api_key(config_record))
        )
        response = client.complete(
            [
                AIMessage(role="system", content=_HERMES_AGENT_SYSTEM_PROMPT),
                AIMessage(
                    role="user",
                    content=json.dumps(
                        {
                            "task": "can_this_manual_required_quote_be_safely_corrected_now",
                            "quote_request": request.model_dump(mode="json"),
                            "quote_result": result.model_dump(mode="json"),
                            "evidence": evidence,
                            "output_schema": {
                                "action": "no_action | use_zone_matrix | use_resolved_manual_quote",
                                "confidence": "0-100 integer",
                                "reason_zh": "short Chinese reason",
                                "origin": "required only for use_zone_matrix",
                                "zone": "required only for use_zone_matrix",
                                "manual_task_id": "required only for use_resolved_manual_quote",
                            },
                        },
                        ensure_ascii=False,
                    ),
                ),
            ]
        )
        if response.error:
            logger.warning("Hermes Agent model call failed.", extra={"quote_id": result.quote_id, "error": response.error})
            return None
        data = _parse_json_object(response.content)
        if data is None:
            return None
        return AgentDecision(
            action=str(data.get("action") or "no_action"),
            confidence=_bounded_int(data.get("confidence"), default=0),
            reason_zh=str(data.get("reason_zh") or "Hermes Agent 未提供原因。")[:500],
            origin=normalize_origin(str(data["origin"])) if data.get("origin") else None,
            zone=_int_value(data.get("zone")),
            manual_task_id=_int_value(data.get("manual_task_id")),
        )

    def _build_evidence(self, request: ZoneQuoteRequest, result: ZoneQuoteResult) -> dict[str, object]:
        city = result.city or request.city
        province = result.province or request.province
        postal_prefix = result.postal_prefix or extract_fsa(request.postal_code)
        expected_origin = ORIGIN_BY_PROVINCE.get(normalize_province(province) or "")
        billing_pallets = result.billing_pallets

        zone_rules = []
        if city and province:
            zone_rules.extend(self.zone_repository.list_city_zone_rules(city, province))
        if postal_prefix and province:
            zone_rules.extend(self.zone_repository.list_postal_family_zone_rules(postal_prefix, province))
        zone_rules.extend(self._province_expected_origin_rules(province, expected_origin))

        zone_options: list[dict[str, object]] = []
        seen_zone_options: set[tuple[str, int, str, str]] = set()
        for rule in zone_rules:
            origin = normalize_origin(rule.origin) or rule.origin
            key = (origin, rule.zone, rule.postal_prefix, rule.city)
            if key in seen_zone_options:
                continue
            seen_zone_options.add(key)
            price_record = (
                self.zone_repository.get_zone_price(origin, rule.zone, billing_pallets)
                if billing_pallets is not None
                else None
            )
            zone_options.append(
                {
                    "postal_prefix": rule.postal_prefix,
                    "city": rule.city,
                    "province": rule.province,
                    "origin": origin,
                    "zone": rule.zone,
                    "expected_origin_match": origin == expected_origin,
                    "has_price_for_billing_pallets": price_record is not None,
                    "base_price_usd": f"{price_record.base_price_usd:.2f}" if price_record else None,
                }
            )

        curated_safe_options = _curated_safe_zone_options(
            zone_options,
            postal_prefix=postal_prefix,
            city=city,
            expected_origin=expected_origin,
        )

        return {
            "postal_prefix": postal_prefix,
            "city": city,
            "province": province,
            "expected_origin": expected_origin,
            "billing_pallets": billing_pallets,
            "zone_options": zone_options[:80],
            "curated_safe_options": curated_safe_options[:12],
            "resolved_manual_tasks": self._resolved_manual_task_evidence(city, province, postal_prefix, billing_pallets),
        }

    def _province_expected_origin_rules(self, province: str | None, expected_origin: str | None) -> list[Any]:
        normalized_province = normalize_province(province)
        if not normalized_province or not expected_origin:
            return []
        records = self.db.scalars(
            select(ZoneLookupRule)
            .where(
                ZoneLookupRule.active.is_(True),
                ZoneLookupRule.province == normalized_province,
                ZoneLookupRule.origin == expected_origin,
            )
            .order_by(ZoneLookupRule.priority.asc(), ZoneLookupRule.postal_prefix.asc(), ZoneLookupRule.id.asc())
            .limit(80)
        ).all()
        return [self.zone_repository._rule_record(record) for record in records]

    def _resolved_manual_task_evidence(
        self,
        city: str | None,
        province: str | None,
        postal_prefix: str | None,
        billing_pallets: int | None,
    ) -> list[dict[str, object]]:
        normalized_city = normalize_city(city)
        normalized_province = normalize_province(province)
        postal_initial = (postal_prefix or "")[:1].upper()
        records = self.db.scalars(
            select(ManualQuoteTask)
            .where(ManualQuoteTask.status == "resolved", ManualQuoteTask.resolved_price_usd.is_not(None))
            .order_by(ManualQuoteTask.updated_at.desc(), ManualQuoteTask.id.desc())
            .limit(120)
        ).all()
        matches: list[dict[str, object]] = []
        for task in records:
            result_json = task.result_json or {}
            request_json = task.request_json or {}
            task_city = normalize_city(_string(result_json.get("city")) or _string(request_json.get("city")))
            task_province = normalize_province(_string(result_json.get("province")) or _string(request_json.get("province")))
            task_prefix = _string(result_json.get("postal_prefix")) or extract_fsa(_string(request_json.get("postal_code")))
            task_pallets = _int_value(result_json.get("billing_pallets"))
            if billing_pallets is not None and task_pallets != billing_pallets:
                continue
            same_city = bool(task_city and normalized_city and task_city == normalized_city and task_province == normalized_province)
            same_initial = bool(task_prefix and postal_initial and task_prefix[:1].upper() == postal_initial and task_province == normalized_province)
            if not same_city and not same_initial:
                continue
            matches.append(
                {
                    "manual_task_id": task.id,
                    "quote_id": task.quote_id,
                    "postal_prefix": task_prefix,
                    "city": task_city,
                    "province": task_province,
                    "origin": result_json.get("origin"),
                    "zone": result_json.get("zone"),
                    "billing_pallets": task_pallets,
                    "resolved_price_usd": f"{Decimal(task.resolved_price_usd):.2f}",
                    "resolved_note": task.resolved_note,
                }
            )
        return matches[:30]

    def _apply_zone_matrix_decision(
        self,
        request: ZoneQuoteRequest,
        original: ZoneQuoteResult,
        decision: AgentDecision,
        evidence: dict[str, object],
    ) -> ZoneQuoteResult:
        if not decision.origin or decision.zone is None or original.billing_pallets is None:
            return original
        if not _zone_option_supported(evidence, decision.origin, decision.zone):
            return original
        price_record = self.zone_repository.get_zone_price(decision.origin, decision.zone, original.billing_pallets)
        if price_record is None:
            return original

        pricing = calculate_zone_price(
            base_price_usd=money(price_record.base_price_usd),
            address_type=request.address_type,
            requires_liftgate=request.requires_liftgate,
            requires_pallet_jack=request.requires_pallet_jack,
            requires_appointment=request.requires_appointment,
            detention_minutes=request.detention_minutes,
            config=self.pricing_config,
        )
        corrected = original.model_copy(
            update={
                "source_type": ZoneQuoteSourceType.HERMES_AGENT_CORRECTION,
                "confidence": max(50, min(decision.confidence, 82)),
                "origin": decision.origin,
                "zone": decision.zone,
                "base_price_usd": money(price_record.base_price_usd),
                "fuel_usd": pricing.fuel_usd,
                "accessorials": pricing.accessorials,
                "total_price_usd": pricing.total_price_usd,
                "manual_review_required": False,
                "risk_tags": sorted(set([*original.risk_tags, "hermes_agent_correction", "hermes_agent_zone_matrix"])),
                "matched_rule": (
                    f"hermes_agent_correction + {decision.origin} Zone {decision.zone} + "
                    f"{original.billing_pallets} pallets"
                ),
                "matched_by": "hermes_agent_zone_matrix",
                "internal_note": (
                    "Hermes Agent 基于 Zone 证据提出纠错，后端校验 origin/zone/price_matrix 后放行；"
                    f"原因：{decision.reason_zh}"
                ),
            }
        )
        corrected.sales_note = build_zone_sales_note(request, corrected)
        return corrected

    def _apply_manual_task_decision(
        self,
        request: ZoneQuoteRequest,
        original: ZoneQuoteResult,
        decision: AgentDecision,
        evidence: dict[str, object],
    ) -> ZoneQuoteResult:
        task = _manual_task_from_evidence(evidence, decision.manual_task_id)
        if task is None:
            return original
        total_price = Decimal(str(task["resolved_price_usd"])).quantize(Decimal("0.01"))
        origin = normalize_origin(_string(task.get("origin"))) or original.origin
        zone = _int_value(task.get("zone")) or original.zone
        corrected = original.model_copy(
            update={
                "source_type": ZoneQuoteSourceType.HERMES_AGENT_CORRECTION,
                "confidence": max(50, min(decision.confidence, 80)),
                "origin": origin,
                "zone": zone,
                "base_price_usd": total_price,
                "fuel_usd": Decimal("0.00"),
                "accessorials": {},
                "total_price_usd": total_price,
                "manual_review_required": False,
                "risk_tags": sorted(set([*original.risk_tags, "hermes_agent_correction", "hermes_agent_manual_history"])),
                "matched_rule": f"hermes_agent_correction + manual_task {decision.manual_task_id}",
                "matched_by": "hermes_agent_manual_history",
                "internal_note": f"Hermes Agent 复用已解决人工任务并通过后端校验；原因：{decision.reason_zh}",
            }
        )
        corrected.sales_note = _manual_history_sales_note(request, corrected)
        return corrected


_HERMES_AGENT_SYSTEM_PROMPT = """你是 Hermes Agent，负责加拿大尾端报价的智能纠错。
你不能发明价格，不能修改客户货物数据，不能绕过后端校验。
你只能在给定 evidence 中选择：
1. use_zone_matrix：选择 evidence.zone_options 里已有的 origin + zone，且必须 has_price_for_billing_pallets=true。
2. use_resolved_manual_quote：选择 evidence.resolved_manual_tasks 里的已解决人工任务。
3. no_action：证据不足，保持人工复核。

evidence.curated_safe_options 是后端根据同省、正确始发仓、邮编邻近、价格矩阵可用性预筛出的纠错候选。
如果 curated_safe_options 非空，且候选说明没有明显矛盾，优先选择排名最高的候选，返回 use_zone_matrix。
不要选择 expected_origin_match=false 的旧始发仓记录。
优先避免错误放价。旧始发仓和省份不一致时要谨慎；如果没有可靠依据，返回 no_action。
只返回 JSON，不要 Markdown，不要解释表格。"""


def _parse_json_object(content: str) -> dict[str, Any] | None:
    text = content.strip()
    if not text:
        return None
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.DOTALL | re.IGNORECASE)
    if fenced:
        text = fenced.group(1)
    elif not text.startswith("{"):
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        text = match.group(0)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _zone_option_supported(evidence: dict[str, object], origin: str, zone: int) -> bool:
    for option in evidence.get("zone_options") or []:
        if not isinstance(option, dict):
            continue
        if option.get("origin") == origin and _int_value(option.get("zone")) == zone and option.get("has_price_for_billing_pallets"):
            return True
    return False


def _manual_task_from_evidence(evidence: dict[str, object], task_id: int | None) -> dict[str, object] | None:
    if task_id is None:
        return None
    for task in evidence.get("resolved_manual_tasks") or []:
        if isinstance(task, dict) and _int_value(task.get("manual_task_id")) == task_id:
            return task
    return None


def _curated_safe_zone_options(
    zone_options: list[dict[str, object]],
    *,
    postal_prefix: str | None,
    city: str | None,
    expected_origin: str | None,
) -> list[dict[str, object]]:
    requested_prefix = _normalize_prefix(postal_prefix)
    if not requested_prefix or not expected_origin:
        return []

    requested_city = normalize_city(city)
    priced_expected_options = [
        option
        for option in zone_options
        if option.get("expected_origin_match")
        and option.get("has_price_for_billing_pallets")
        and option.get("origin") == expected_origin
    ]
    if not priced_expected_options:
        return []

    curated: list[dict[str, object]] = []
    same_city_options = [
        option
        for option in priced_expected_options
        if requested_city and normalize_city(_string(option.get("city"))) == requested_city
    ]
    curated.extend(
        _group_safe_options(
            same_city_options,
            reason="同城市且始发仓匹配，价格矩阵有对应托数。",
            basis="same_city_expected_origin",
            confidence_ceiling=82,
            min_support=1,
        )
    )

    nearest_options = _nearest_relaxed_prefix_options(priced_expected_options, requested_prefix)
    curated.extend(
        _group_safe_options(
            nearest_options,
            reason=(
                f"邮编前缀 {requested_prefix} 未命中；采用同省同首字母的最近邮编锚点，"
                "且始发仓匹配、价格矩阵有对应托数。"
            ),
            basis="nearest_postal_initial_expected_origin",
            confidence_ceiling=76,
            min_support=2,
        )
    )

    by_key: dict[tuple[str, int], dict[str, object]] = {}
    for option in curated:
        origin = _string(option.get("origin"))
        zone = _int_value(option.get("zone"))
        if origin is None or zone is None:
            continue
        key = (origin, zone)
        existing = by_key.get(key)
        if existing is None or int(option.get("support_count") or 0) > int(existing.get("support_count") or 0):
            by_key[key] = option

    return sorted(
        by_key.values(),
        key=lambda item: (
            -_int_value(item.get("confidence_ceiling")) if _int_value(item.get("confidence_ceiling")) is not None else 0,
            -_int_value(item.get("support_count")) if _int_value(item.get("support_count")) is not None else 0,
            _int_value(item.get("zone")) or 99,
        ),
    )


def _group_safe_options(
    options: list[dict[str, object]],
    *,
    reason: str,
    basis: str,
    confidence_ceiling: int,
    min_support: int,
) -> list[dict[str, object]]:
    groups: dict[tuple[str, int], list[dict[str, object]]] = {}
    for option in options:
        origin = _string(option.get("origin"))
        zone = _int_value(option.get("zone"))
        if origin is None or zone is None:
            continue
        groups.setdefault((origin, zone), []).append(option)

    curated: list[dict[str, object]] = []
    for (origin, zone), group in groups.items():
        prefixes = sorted({_normalize_prefix(_string(option.get("postal_prefix"))) for option in group if option.get("postal_prefix")})
        cities = sorted({_string(option.get("city")) or "" for option in group if option.get("city")})
        if len(prefixes) < min_support and len(cities) < min_support:
            continue
        sample = group[0]
        curated.append(
            {
                "origin": origin,
                "zone": zone,
                "base_price_usd": sample.get("base_price_usd"),
                "basis": basis,
                "confidence_ceiling": confidence_ceiling,
                "support_count": len(group),
                "supporting_prefixes": prefixes[:12],
                "supporting_cities": cities[:12],
                "reason_zh": reason,
            }
        )
    return curated


def _nearest_relaxed_prefix_options(
    options: list[dict[str, object]],
    requested_prefix: str,
) -> list[dict[str, object]]:
    scored: list[tuple[int, dict[str, object]]] = []
    for option in options:
        prefix = _normalize_prefix(_string(option.get("postal_prefix")))
        distance = _relaxed_prefix_distance(prefix, requested_prefix)
        if distance is None:
            continue
        scored.append((distance, option))
    if not scored:
        return []
    nearest = min(distance for distance, _ in scored)
    return [option for distance, option in scored if distance == nearest]


def _relaxed_prefix_distance(candidate: str, requested: str) -> int | None:
    if not candidate or not requested or candidate[0] != requested[0]:
        return None
    if len(candidate) >= 2 and len(requested) >= 2 and candidate[:2] == requested[:2]:
        if len(candidate) >= 3 and len(requested) >= 3:
            return abs(_prefix_rank(candidate[2]) - _prefix_rank(requested[2]))
        return 0
    if len(candidate) < 2 or len(requested) < 2:
        return 100
    return 100 + abs(_prefix_rank(candidate[1]) - _prefix_rank(requested[1])) * 10


def _prefix_rank(value: str) -> int:
    if value.isdigit():
        return ord(value) - ord("0")
    return 10 + ord(value.upper()) - ord("A")


def _normalize_prefix(value: str | None) -> str:
    return (value or "").upper().replace(" ", "")[:3]


def _manual_history_sales_note(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> str:
    return "\n".join(
        [
            "加拿大尾端派送报价：",
            f"目的地：{request.address_line or ''}, {result.city or ''}, {result.province or ''} {result.postal_code or ''}".strip(),
            f"货物总计：共{request.piece_count}件，{request.cbm} CBM，{request.weight_kg} KG，计费{result.billing_pallets}托",
            f"报价：USD {result.total_price_usd}（{origin_label(result.origin)}派送）",
            "注：不带尾板，自卸货",
            "- 送货到门口路边，不含其他操作",
            "- 无卸货平台需尾板 +50USD/票",
            "- 需手叉车配合 +50USD/票",
            "- 免费等待30分钟，超时35USD/半小时",
            "- 价格以供应商实测地址及卡车准入情况为准",
            "- 下单引用单号，未引用加收50人民币/票服务费",
        ]
    )


def _bounded_int(value: object, *, default: int) -> int:
    number = _int_value(value)
    if number is None:
        return default
    return max(0, min(number, 100))


def _int_value(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        number = int(Decimal(str(value)))
    except Exception:
        return None
    return number


def _string(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
