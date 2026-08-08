"""AI-assisted FCL field extraction with a deterministic, price-free fallback."""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal
from typing import Any

from packages.ai_assistant.model_client import AIMessage, BaseAIClient
from packages.quote_engine.fcl import FCLCargoItem, FCLContainerInput, FCLQuoteDraft


class FCLExtractionError(RuntimeError):
    pass


FCL_EXTRACTION_SYSTEM_PROMPT = """
你只负责从客户询价中提取和规范化整柜物流字段，不得计算或输出任何价格、费用、利润、汇率或合计。
只输出 JSON，字段必须来自 schema：customer_name, contact, pol, pod, containers,
cargo_name, cargo_items, declared_piece_count, declared_total_weight_kg,
declared_total_volume_cbm, special_attributes, ready_date, target_etd, carrier,
service_preference, service_scope, notes, confidence, extraction_notes，以及以下可选字段：
customer_type, destination_postal_code, destination_address, cargo_details,
cargo_value, cargo_value_currency, hs_code, origin_country, stackable,
sds_un_info, wood_packaging, expected_delivery_date, deadline_strictness,
acceptable_transit_days, trade_terms, export_declaration, importer_exists,
importer_legal_name, bn_rm_status, carm_status, has_broker, service_stages,
tax_included, priority_goal, address_type, tail_lift, appointment_window,
forklift, platform_warehouse, declaration_acknowledged。
尺寸和重量可以保留原单位，数量必须是正整数；没有证据就填 null/空数组，不要猜。
""".strip()


def extract_fcl_draft(customer_message: str, client: BaseAIClient | None = None) -> FCLQuoteDraft:
    deterministic = parse_fcl_text(customer_message)
    if client is None:
        return deterministic
    try:
        model = _extract_with_ai(customer_message, client)
    except FCLExtractionError as exc:
        deterministic.extraction_notes.append(f"ai_extraction_failed:{exc.__class__.__name__}")
        return deterministic
    return _merge_without_overriding_explicit_facts(deterministic, model)


def parse_fcl_text(customer_message: str) -> FCLQuoteDraft:
    text = customer_message.strip()
    if not text:
        return FCLQuoteDraft(extraction_notes=["empty_input"])
    parsed_json = _parse_json_input(text)
    if parsed_json is not None:
        try:
            draft = FCLQuoteDraft.model_validate(parsed_json)
            draft.extraction_notes.append("structured_json_input")
            draft.confidence = max(draft.confidence, 90)
            return draft
        except Exception:
            pass

    pol = _line_value(text, r"(?:POL|起运港|装货港)")
    pod = _line_value(text, r"(?:POD|目的港|卸货港)")
    cargo_name = _line_value(text, r"(?:货名|品名|commodity)")
    carrier = _line_value(text, r"(?:船东|船公司|carrier)")
    service_preference = _line_value(text, r"(?:渠道|服务偏好|service)")
    customer_type = _keyword_enum(
        text,
        (("进口商", "importer"), ("出口商", "exporter"), ("平台卖家", "platform_seller"), ("货代同行", "forwarder"), ("仓库", "warehouse"), ("其他", "other")),
    )
    destination_postal_code = _postal_code(text)
    destination_address = _line_value(text, r"(?:完整收货地址|收货地址|地址)")
    cargo_details = _line_value(text, r"(?:材质|用途|品牌|型号)")
    cargo_value, cargo_value_currency = _cargo_value(text)
    hs_code = _hs_code(text)
    origin_country = _line_value(text, r"(?:原产地|产地)")
    stackable = _stackable(text)
    sds_un_info = _line_value(text, r"(?:SDS|UN\s*编号|电池资料)")
    wood_packaging = _keyword_enum(
        text,
        (("待确认", "unknown"), ("合规木包装", "compliant"), ("无木", "none")),
    )
    expected_delivery_date = _date_value(text, r"(?:期望到门|最迟到门|期望送达)")
    deadline_strictness = _keyword_enum(text, (("硬性", "hard"), ("可协商", "negotiable"), ("仅参考", "reference")))
    acceptable_transit_days = _integer_value(text, r"(?:可接受中转|中转|待拼)\s*(?:天数|天)")
    trade_terms = _trade_terms(text)
    export_declaration = _keyword_enum(
        text,
        (("需平台安排", "platform"), ("客户可报关", "customer"), ("待确认", "pending")),
    )
    importer_exists = _importer_exists(text)
    importer_legal_name = _line_value(text, r"(?:进口商法定名称|进口主体)")
    bn_rm_status = _keyword_enum(text, (("申请中", "applying"), ("齐备", "ready"), ("不清楚", "unknown"), ("无", "none")))
    carm_status = _keyword_enum(text, (("待授权", "pending"), ("齐备", "ready"), ("不清楚", "unknown")))
    has_broker = _keyword_enum(text, (("需平台安排", "need_platform"), ("有报关行", "yes"), ("已有报关行", "yes")))
    tax_included = _keyword_enum(text, (("需要比较", "compare"), ("包税：是", "yes"), ("包税：否", "no")))
    priority_goal = _keyword_enum(text, (("经济", "economy"), ("时效", "speed"), ("稳定", "stable"), ("平衡", "balanced")))
    address_type = _keyword_enum(text, (("Amazon", "amazon"), ("仓库", "warehouse"), ("住宅", "residential"), ("商业", "commercial")))
    tail_lift = _keyword_enum(text, (("尾板需求：不需要", "no"), ("尾板：不需要", "no"), ("不需要尾板", "no"), ("尾板", "yes")))
    appointment_window = _line_value(text, r"(?:预约|时间窗)")
    forklift = _keyword_enum(text, (("无叉车", "no"), ("无装卸平台", "no"), ("叉车", "yes"), ("装卸平台", "yes")))
    platform_warehouse = _line_value(text, r"(?:平台仓|FBA|亚马逊仓)")
    service_stages = _service_stages(text)
    piece_count = _integer_value(text, r"(?:总件数|件数|数量|pieces?)")
    total_weight, weight_unit = _measure_value(text, r"(?:总毛重|毛重|总重量|重量|gross\s*weight)")
    total_volume, _ = _measure_value(text, r"(?:总体积|体积|方量|cbm|m3)")
    service_scope = _service_scope(text)
    target_etd = _date_value(text, r"(?:目标\s*ETD|ETD|开船日期|船期)")
    ready_date = _date_value(text, r"(?:备货日期|ready)")

    containers = _containers(text)
    cargo_items = _cargo_items(text)
    if not cargo_items and total_weight is not None:
        cargo_items = [
            FCLCargoItem(
                name=cargo_name,
                quantity=piece_count or 1,
                weight=total_weight if (piece_count or 1) == 1 else None,
                weight_unit=_normalize_weight_unit(weight_unit),
                total_weight_kg=_to_kg(total_weight, weight_unit),
            )
        ]

    special_attributes = [
        label
        for keyword, label in (
            ("危险品", "dangerous_goods"),
            ("危品", "dangerous_goods"),
            ("带电", "battery"),
            ("带磁", "magnetic"),
            ("液体", "liquid"),
            ("粉末", "powder"),
            ("食品", "food"),
            ("木制品", "wood"),
            ("品牌", "branded"),
            ("冷藏", "reefer"),
            ("冷冻", "reefer"),
            ("超尺寸", "oversized"),
            ("超长", "oversized"),
            ("普货", "general_cargo"),
        )
        if keyword in text
    ]
    notes = _line_value(text, r"(?:备注|说明|note)")
    return FCLQuoteDraft(
        pol=pol,
        pod=pod,
        destination_postal_code=destination_postal_code,
        destination_address=destination_address,
        containers=containers,
        cargo_name=cargo_name,
        cargo_details=cargo_details,
        cargo_items=cargo_items,
        declared_piece_count=piece_count,
        declared_total_weight_kg=_to_kg(total_weight, weight_unit),
        declared_total_volume_cbm=total_volume,
        cargo_value=cargo_value,
        cargo_value_currency=cargo_value_currency,
        hs_code=hs_code,
        origin_country=origin_country,
        stackable=stackable,
        special_attributes=sorted(set(special_attributes)),
        sds_un_info=sds_un_info,
        wood_packaging=wood_packaging,
        ready_date=ready_date,
        target_etd=target_etd,
        expected_delivery_date=expected_delivery_date,
        deadline_strictness=deadline_strictness,
        acceptable_transit_days=acceptable_transit_days,
        carrier=carrier,
        service_preference=service_preference,
        service_scope=service_scope,
        service_stages=service_stages,
        trade_terms=trade_terms,
        export_declaration=export_declaration,
        importer_exists=importer_exists,
        importer_legal_name=importer_legal_name,
        bn_rm_status=bn_rm_status,
        carm_status=carm_status,
        has_broker=has_broker,
        tax_included=tax_included,
        priority_goal=priority_goal,
        address_type=address_type,
        tail_lift=tail_lift,
        appointment_window=appointment_window,
        forklift=forklift,
        platform_warehouse=platform_warehouse,
        notes=notes,
        confidence=60 if any((pol, pod, containers, cargo_items)) else 0,
        extraction_notes=["deterministic_text_parser"],
    )


def _extract_with_ai(customer_message: str, client: BaseAIClient) -> FCLQuoteDraft:
    response = client.complete(
        [
            AIMessage(role="system", content=FCL_EXTRACTION_SYSTEM_PROMPT),
            AIMessage(role="user", content=customer_message),
        ]
    )
    if response.error:
        raise FCLExtractionError(response.error)
    try:
        data = _parse_json_object(response.content)
        return FCLQuoteDraft.model_validate(data)
    except Exception as exc:
        raise FCLExtractionError("FCL extraction output failed schema validation") from exc


def _merge_without_overriding_explicit_facts(base: FCLQuoteDraft, ai: FCLQuoteDraft) -> FCLQuoteDraft:
    values = base.model_dump()
    ai_values = ai.model_dump()
    for key, value in ai_values.items():
        current = values.get(key)
        if _empty(current) and not _empty(value):
            values[key] = value
    values["confidence"] = max(base.confidence, min(ai.confidence, 85))
    values["extraction_notes"] = list(dict.fromkeys([*base.extraction_notes, "ai_extraction_used", *ai.extraction_notes]))
    return FCLQuoteDraft.model_validate(values)


def _containers(text: str) -> list[FCLContainerInput]:
    found: list[FCLContainerInput] = []
    patterns = (
        r"(?P<quantity>\d+)\s*[xX*]?\s*(?P<container>20\s*(?:GP|DC|DV)|40\s*(?:GP|HC|HQ|DC)|45\s*(?:HC|HQ))",
        r"(?P<container>20\s*(?:GP|DC|DV)|40\s*(?:GP|HC|HQ|DC)|45\s*(?:HC|HQ))\s*[xX*]?\s*(?P<quantity>\d+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            found.append(FCLContainerInput(container_type=match.group("container"), quantity=int(match.group("quantity"))))
        if found:
            break
    return found


def _cargo_items(text: str) -> list[FCLCargoItem]:
    items: list[FCLCargoItem] = []
    pattern = re.compile(
        r"(?:(?P<quantity>\d+)\s*[件个]?\s*)?(?P<length>\d+(?:\.\d+)?)\s*[x×*]\s*(?P<width>\d+(?:\.\d+)?)\s*[x×*]\s*(?P<height>\d+(?:\.\d+)?)(?:\s*(?P<unit>mm|cm|m|in|英寸))?",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        items.append(
            FCLCargoItem(
                quantity=int(match.group("quantity") or 1),
                length=Decimal(match.group("length")),
                width=Decimal(match.group("width")),
                height=Decimal(match.group("height")),
                dimension_unit=_normalize_dimension_unit(match.group("unit")),
            )
        )
    return items


def _line_value(text: str, label_pattern: str) -> str | None:
    match = re.search(rf"{label_pattern}\s*[:：=]?\s*([^\n,，;；]+)", text, flags=re.IGNORECASE)
    return match.group(1).strip() if match and match.group(1).strip() else None


def _integer_value(text: str, label_pattern: str) -> int | None:
    for pattern in (
        rf"{label_pattern}\s*[:：=]?\s*(\d+)",
        r"(?:^|[\s,，;；])(\d+)\s*(?:件|pcs|pieces?)(?=[\s,，;；。]|$)",
    ):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
    return None


def _measure_value(text: str, label_pattern: str) -> tuple[Decimal | None, str]:
    match = re.search(rf"{label_pattern}\s*[:：=]?\s*([0-9]+(?:\.[0-9]+)?)\s*(kg|公斤|吨|t|lb|磅|cbm|m3|立方米|方)?", text, flags=re.IGNORECASE)
    if not match:
        return None, "kg"
    unit = (match.group(2) or "kg").lower()
    return Decimal(match.group(1)), unit


def _service_scope(text: str) -> str | None:
    for pattern, value in (
        (r"port\s*[- ]?to\s*[- ]?port|港到港", "port-to-port"),
        (r"door\s*[- ]?to\s*[- ]?port|门到港", "door-to-port"),
        (r"port\s*[- ]?to\s*[- ]?door|港到门", "port-to-door"),
        (r"door\s*[- ]?to\s*[- ]?door|门到门", "door-to-door"),
    ):
        if re.search(pattern, text, flags=re.IGNORECASE):
            return value
    return None


def _keyword_enum(text: str, mappings: tuple[tuple[str, str], ...]) -> str | None:
    for keyword, value in mappings:
        if keyword.lower() in text.lower():
            return value
    return None


def _postal_code(text: str) -> str | None:
    match = re.search(r"邮编\s*[:：=]?\s*([A-Za-z0-9]+\s*[A-Za-z0-9]*)", text)
    if match:
        return match.group(1).upper()
    match = re.search(r"\b[A-Za-z]\d[A-Za-z][ ]?\d[A-Za-z]\d\b", text)
    return match.group(0).upper() if match else None


def _cargo_value(text: str) -> tuple[Decimal | None, str | None]:
    match = re.search(
        r"货值\s*[:：=]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(USD|CAD|CNY|美元|加元|人民币)?",
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        return None, None
    currency = match.group(2)
    if currency is None:
        return Decimal(match.group(1).replace(",", "")), None
    return Decimal(match.group(1).replace(",", "")), {"美元": "USD", "加元": "CAD", "人民币": "CNY"}.get(currency.upper(), currency.upper())


def _hs_code(text: str) -> str | None:
    match = re.search(r"(?:HS\s*编码|HS)\s*[:：=]?\s*([0-9.]+)", text, flags=re.IGNORECASE)
    return "".join(character for character in match.group(1) if character.isdigit()) if match else None


def _stackable(text: str) -> bool | None:
    match = re.search(r"叠放\s*[:：=]?\s*(是|否|可以|不可以)", text)
    if not match:
        return None
    return match.group(1) in {"是", "可以"}


def _trade_terms(text: str) -> str | None:
    match = re.search(r"贸易条款\s*[:：=]?\s*([A-Za-z]{3}|其他)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return {"其他": "OTHER"}.get(match.group(1).upper(), match.group(1).upper())


def _importer_exists(text: str) -> str | None:
    match = re.search(r"进口商\s*[:：=]?\s*(有|是|无|没有|否|不确定|待确认)", text)
    if match:
        return {"有": "yes", "是": "yes", "无": "no", "没有": "no", "否": "no", "不确定": "unknown", "待确认": "unknown"}[match.group(1)]
    if "没有进口商" in text or "无进口商" in text:
        return "no"
    if "不确定" in text and "进口商" in text:
        return "unknown"
    if "有加拿大进口商" in text or "有进口商" in text:
        return "yes"
    return None


def _service_stages(text: str) -> list[str]:
    return sorted(
        {
            value
            for keyword, value in (
                ("提货", "pickup"),
                ("海运", "ocean"),
                ("清关", "customs"),
                ("仓储", "warehousing"),
                ("派送", "delivery"),
                ("全程", "door_to_door"),
            )
            if keyword in text
        }
    )


def _date_value(text: str, label_pattern: str) -> date | None:
    match = re.search(rf"{label_pattern}\s*[:：=]?\s*(\d{{4}}[-/.]\d{{1,2}}[-/.]\d{{1,2}}|\d{{1,2}}[-/.]\d{{1,2}})", text, flags=re.IGNORECASE)
    if not match:
        return None
    raw = match.group(1).replace("/", "-").replace(".", "-")
    parts = raw.split("-")
    if len(parts) == 2:
        raw = f"{date.today().year}-{int(parts[0]):02d}-{int(parts[1]):02d}"
    else:
        raw = f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return None


def _parse_json_input(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _parse_json_object(text: str) -> dict[str, Any]:
    cleaned = re.sub(r"```(?:json)?", "", text, flags=re.IGNORECASE).replace("```", "").strip()
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Expected JSON object")
    return value


def _empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _normalize_dimension_unit(value: str | None) -> str:
    return {None: "cm", "": "cm", "英寸": "in"}.get((value or "").lower(), (value or "cm").lower())


def _normalize_weight_unit(value: str) -> str:
    return {"公斤": "kg", "吨": "kg", "t": "kg", "磅": "lb"}.get(value, value if value in {"g", "kg", "lb"} else "kg")


def _to_kg(value: Decimal | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    normalized = _normalize_weight_unit(unit)
    if normalized == "lb":
        return value * Decimal("0.45359237")
    if normalized == "g":
        return value / Decimal("1000")
    return value * Decimal("1000") if unit in {"吨", "t"} else value
