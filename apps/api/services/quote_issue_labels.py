RISK_TAG_LABELS: dict[str, str] = {
    "manual_required": "需要人工确认",
    "postal_prefix_missing": "无法识别加拿大邮编前缀",
    "zone_not_found": "未命中邮编分区",
    "zone_price_not_found": "未命中 Zone 价格矩阵",
    "city_zone_fallback": "按城市/省份匹配 Zone",
    "city_zone_prefix_family_fallback": "按同邮编族缩小城市 Zone",
    "postal_family_fallback": "按同省邮编族模糊匹配 Zone",
    "nearest_postal_prefix_fallback": "采用最近邮编前缀锚点",
    "learned_quote_reused": "复用人工确认学习记录",
    "learned_from_manual_task": "来源为已处理人工任务",
    "billing_pallets_manual_required": "计费托数需人工确认",
    "missing_billable_pallet_basis": "缺少计费托数依据",
    "flat_rate_packaging_required": "特殊包装需按整托/人工确认",
    "stale_origin_overridden": "始发仓已按省份规则覆盖",
    "split_record_conflict": "邮编存在拆分记录冲突",
    "ai_extraction_failed": "AI 字段提取失败",
    "ai_missing_fields": "AI 缺少必要字段",
    "postal_code": "缺少加拿大邮编",
    "cbm": "缺少总体积 CBM",
    "weight_kg": "缺少总重量 KG",
    "piece_count": "缺少件数",
    "packaging_type": "缺少包装类型",
    "longest_side_cm": "缺少最大单边尺寸",
    "explicit_pallet_count": "缺少托盘数量",
    "is_stackable": "缺少是否可堆叠",
    "address_type": "缺少地址类型",
    "city": "缺少城市",
    "province": "缺少省份",
    "requires_liftgate": "缺少是否需要尾板",
    "requires_pallet_jack": "缺少是否需要手叉车",
    "requires_appointment": "缺少是否需要预约",
}


def risk_tag_label(tag: str) -> str:
    return RISK_TAG_LABELS.get(tag, tag)


def risk_tag_labels(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    return [risk_tag_label(tag) for tag in tags or []]


def localize_issue_reason(reason: str | None) -> str | None:
    if not reason:
        return reason
    if reason.startswith("No zone rule found for postal prefix "):
        prefix = reason.removeprefix("No zone rule found for postal prefix ").rstrip(".")
        return f"未命中邮编前缀 {prefix} 的 Zone 分区规则，需要人工确认或补充价格表。"
    if reason.startswith("No zone rule matched "):
        detail = reason.removeprefix("No zone rule matched ").rstrip(".")
        return f"邮编/城市/省份组合未匹配到 Zone 分区规则：{detail}。"
    if reason.startswith("Split-record conflict for "):
        prefix = reason.split(";", 1)[0].removeprefix("Split-record conflict for ")
        return f"邮编前缀 {prefix} 存在拆分记录冲突，城市/省份无法唯一确定 Zone。"
    if reason.startswith("Multiple zone rules matched "):
        prefix = reason.removeprefix("Multiple zone rules matched ").split(";", 1)[0]
        return f"邮编前缀 {prefix} 匹配到多个 Zone 规则，需要人工确认。"
    if reason.startswith("No zone matrix price for "):
        detail = reason.removeprefix("No zone matrix price for ").rstrip(".")
        return f"Zone 价格矩阵缺少价格：{detail}。"
    if reason == "Postal prefix could not be extracted.":
        return "无法从邮编中识别加拿大 FSA/邮编前缀，需要人工确认。"
    if reason == "Billing pallets require manual review.":
        return "计费托数无法自动确定，需要人工确认。"
    return reason
