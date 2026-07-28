from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from packages.quote_engine.zone_lookup import origin_label
from packages.quote_engine.zone_models import ZoneQuoteRequest, ZoneQuoteResult


def attach_zone_quote_logic(request: ZoneQuoteRequest, result: ZoneQuoteResult) -> ZoneQuoteResult:
    trace = dict(result.match_trace or {})
    trace["quote_logic"] = build_zone_quote_logic(request.model_dump(mode="json"), result.model_dump(mode="json"))
    return result.model_copy(update={"match_trace": trace})


def build_zone_quote_logic(request_json: dict[str, Any], result_json: dict[str, Any]) -> dict[str, object]:
    manual_required = bool(result_json.get("manual_review_required"))
    source_type = _text(result_json.get("source_type")) or "unknown"
    origin = _text(result_json.get("origin"))
    zone = result_json.get("zone")
    billing_pallets = result_json.get("billing_pallets")
    base_price = _money_text(result_json.get("base_price_usd"))
    fuel = _money_text(result_json.get("fuel_usd"))
    total = _money_text(result_json.get("total_price_usd"))
    matched_rule = _text(result_json.get("matched_rule")) or "未返回匹配说明"
    pallet_breakdown = result_json.get("pallet_breakdown") if isinstance(result_json.get("pallet_breakdown"), dict) else {}
    accessorials = result_json.get("accessorials") if isinstance(result_json.get("accessorials"), dict) else {}

    route = _route_text(origin, zone)
    cargo = (
        f"{request_json.get('piece_count') or '-'}件 / "
        f"{request_json.get('cbm') or '-'} CBM / "
        f"{request_json.get('weight_kg') or '-'} KG"
    )

    if manual_required:
        headline = "系统未放价，需人工确认后才能发客户。"
        next_action = _manual_next_action(request_json, result_json)
        steps = [
            f"货物数据：{cargo}，系统估算计费托数 {billing_pallets or '待确认'} 托。",
            f"地址线索：{result_json.get('postal_prefix') or '-'} / {result_json.get('city') or '-'} / {result_json.get('province') or '-'}。",
            f"未放价原因：{matched_rule}",
            next_action,
            "人工确认后才进入 Hermes 学习候选；批准发布后，后续相同场景才能自动复用。",
        ]
        return {
            "status": "manual_required",
            "headline": headline,
            "price_source": "未锁价",
            "route": route,
            "cargo": cargo,
            "pallet_breakdown": pallet_breakdown,
            "price_formula": "未命中可放价规则，不能自动生成金额。",
            "next_action": next_action,
            "steps": steps,
            "matched_rule": matched_rule,
        }

    price_source = _source_label(source_type)
    formula_parts = [part for part in [f"基础价 {base_price}", f"燃油 {fuel}"] if part]
    if accessorials:
        formula_parts.append(
            "附加费 "
            + " + ".join(f"{key} {_money_text(value)}" for key, value in accessorials.items() if _money_text(value))
        )
    formula = " + ".join(formula_parts) + (f" = 合计 {total}" if total else "")
    steps = [
        f"货物数据：{cargo}，计费托数 {billing_pallets or '-'} 托。",
        f"线路来源：{route}。",
        f"价格来源：{price_source}。",
        f"计算方式：{formula or '后端已锁价，明细未返回'}。",
        f"匹配规则：{matched_rule}",
    ]
    return {
        "status": "quoted",
        "headline": f"报价已由系统规则锁定，合计 {total or '未返回'}。",
        "price_source": price_source,
        "route": route,
        "cargo": cargo,
        "pallet_breakdown": pallet_breakdown,
        "price_formula": formula,
        "next_action": "可发客户；如地址类型、卸货条件或复重复尺变化，需要重新报价。",
        "steps": steps,
        "matched_rule": matched_rule,
    }


def _manual_next_action(request_json: dict[str, Any], result_json: dict[str, Any]) -> str:
    origin = _text(result_json.get("origin"))
    zone = result_json.get("zone")
    billing_pallets = result_json.get("billing_pallets")
    match_trace = result_json.get("match_trace") if isinstance(result_json.get("match_trace"), dict) else {}
    suggested_origin = _text(match_trace.get("suggested_origin"))
    suggested_zone = match_trace.get("suggested_zone")
    suggested_prefix = _text(match_trace.get("suggested_postal_prefix"))
    risk_tags = result_json.get("risk_tags") if isinstance(result_json.get("risk_tags"), list) else []
    if "zone_price_disabled" in risk_tags and origin and zone is not None:
        destination = _destination_text(request_json, result_json)
        return (
            f"目的地 {destination} 已命中 {origin_label(origin) or origin} 始发仓 Zone {zone}，"
            "但该分区已暂停自动报价；请确认最新行情后再放价或在价格配置中重新开启。"
        )
    if "zone_rule_province_mismatch" in risk_tags:
        invalid_examples = match_trace.get("invalid_rule_examples")
        example = invalid_examples[0] if isinstance(invalid_examples, list) and invalid_examples else {}
        invalid_prefix = _text(example.get("postal_prefix")) if isinstance(example, dict) else ""
        return (
            f"检测到无关的跨省脏记录：邮编前缀 {invalid_prefix or suggested_prefix or '-'}；已忽略该记录。"
            "请补充当前邮编前缀 + 城市 + 省份对应的正式 Zone 规则，确认后再放价。"
        )
    if "city_zone_prefix_family_low_support" in risk_tags and suggested_origin and suggested_zone is not None:
        return (
            f"系统只找到相邻邮编锚点 {suggested_prefix or '-'} -> "
            f"{origin_label(suggested_origin) or suggested_origin} Zone {suggested_zone}，"
            "证据不足，需人工确认后再决定是否发布为 Hermes 学习经验。"
        )
    if "zone_price_not_found" in risk_tags and origin and zone is not None:
        return f"建议先核对 {origin_label(origin) or origin} Zone {zone} 的 {billing_pallets or '对应'} 托价格矩阵，确认后补价。"
    if "zone_not_found" in risk_tags or origin is None or zone is None:
        return "建议先核对邮编前缀、城市、省份和始发仓，再确认应落的 Zone。"
    return "建议人工核对 Zone、托数、地址类型和附加服务，确认金额后再发客户。"


def _source_label(source_type: str) -> str:
    return {
        "zone_matrix": "Zone 价格矩阵",
        "llm_auxiliary_advice": "LLM 辅助建议，后端曾校验后放行",
        "hermes_agent_correction": "历史 LLM 辅助建议，后端曾校验后放行",
        "learned_manual_quote": "人工确认后的学习规则",
        "manual_required": "需要人工确认",
    }.get(source_type, source_type)


def _route_text(origin: str | None, zone: object) -> str:
    origin_text = origin_label(origin) or origin or "待确认始发仓"
    zone_text = f"Zone {zone}" if zone is not None else "Zone 待确认"
    return f"{origin_text} / {zone_text}"


def _destination_text(request_json: dict[str, Any], result_json: dict[str, Any]) -> str:
    parts = [
        result_json.get("city") or request_json.get("city"),
        result_json.get("province") or request_json.get("province"),
        result_json.get("postal_code") or request_json.get("postal_code"),
    ]
    return ", ".join(str(part) for part in parts if part) or "待确认目的地"


def _money_text(value: object) -> str | None:
    if value is None or value == "":
        return None
    try:
        return f"USD {Decimal(str(value)).quantize(Decimal('0.01'))}"
    except (InvalidOperation, ValueError):
        return f"USD {value}"


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
