from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from packages.quote_engine.zone_config import ZonePricingConfig


class WorkbenchOption(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    value: str
    label: str


class ProvinceAlias(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    code: str
    name: str
    aliases: list[str]


class WorkbenchParserConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dimension_separators: list[str] = Field(default_factory=lambda: ["*", "x", "X", "×"])
    allow_space_dimension_separator: bool = True
    weight_units: list[str] = Field(default_factory=lambda: ["kg", "kgs"])
    postal_code_pattern: str = r"[A-Za-z]\d[A-Za-z][ -]?\d[A-Za-z]\d"
    country_aliases: list[str] = Field(default_factory=lambda: ["canada", "加拿大"])
    default_country: str = "加拿大"


class WorkbenchQuoteDefaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packaging_type: str = "unknown"
    address_type: str = "commercial"
    is_stackable: bool | None = None
    explicit_pallet_count: int | None = None
    requires_liftgate: bool = False
    requires_pallet_jack: bool = False
    requires_appointment: bool = False
    detention_minutes: int = 0
    notify_wecom: bool = False


class WorkbenchRiskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    dense_density_kg_per_cbm: float = 200
    light_density_kg_per_cbm: float = 100
    oversized_longest_side_cm: float = 240
    heavy_single_piece_kg: float = 500
    core_city_names: list[str] = Field(
        default_factory=lambda: [
            "Toronto",
            "Mississauga",
            "Brampton",
            "Concord",
            "Vaughan",
            "Richmond",
            "Burnaby",
            "Vancouver",
            "Calgary",
            "Edmonton",
            "Montreal",
            "Ottawa",
        ]
    )


class WorkbenchCopyTemplateConfig(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")

    currency_code: str = "USD"
    valid_days: int = 7
    manual_price_text: str = "需要人工复核"
    included_items: list[str] = Field(
        default_factory=lambda: [
            "基础派送费",
            "燃油附加费",
            "常规派送操作费",
        ]
    )
    excluded_items: list[str] = Field(
        default_factory=lambda: [
            "住宅附加费",
            "尾板费",
            "预约费",
            "室内派送费",
            "偏远地区附加费",
            "因地址类型、卸货条件、实际复重复尺产生的额外费用",
        ]
    )
    remark: str = (
        "此报价基于当前提供的尺寸、重量和邮编自动生成。如派送地址为住宅、"
        "小镇偏远区域、无卸货设备或需预约派送，最终费用可能调整。"
    )


class QuoteWorkbenchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = "加拿大尾端 AI 报价系统"
    subtitle: str = "粘贴货物尺寸、重量、派送地址，AI 自动识别并生成报价"
    input_title: str = "AI 智能报价输入"
    input_label: str = "请直接粘贴报价信息"
    primary_button_label: str = "开始智能报价"
    clear_button_label: str = "清空内容"
    import_button_label: str = "导入 Excel"
    status_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "idle": "待识别",
            "parsing": "识别中",
            "parsed": "已解析",
            "quoting": "报价中",
            "quoted": "报价完成",
            "manual_required": "需要人工复核",
        }
    )
    sample_input: str = (
        "170*140*87  409.8kg\n"
        "170*140*74  360.5KG\n"
        "170*87*82   221.5KG\n"
        "71*61*71    92.5KG\n"
        "71*61*71    68.5KG\n"
        "71*61*71    95KG\n"
        "71*61*71    169KG\n"
        "205 Main Street\n"
        "New Norway Alberta Canada\n"
        "T0B 3L0"
    )
    format_hints: list[str] = Field(
        default_factory=lambda: [
            "170*140*87 409.8kg",
            "170x140x87 409.8 KG",
            "170 140 87 409.8kg",
            "地址 + 城市 + 省份 + 邮编",
        ]
    )
    packaging_options: list[WorkbenchOption] = Field(
        default_factory=lambda: [
            WorkbenchOption(value="carton", label="纸箱"),
            WorkbenchOption(value="wooden_crate", label="木箱"),
            WorkbenchOption(value="pallet", label="托盘"),
            WorkbenchOption(value="woven_bag", label="编织袋"),
            WorkbenchOption(value="flexible_packaging", label="软包装"),
            WorkbenchOption(value="unknown", label="待确认"),
        ]
    )
    address_type_options: list[WorkbenchOption] = Field(
        default_factory=lambda: [
            WorkbenchOption(value="commercial", label="商业地址"),
            WorkbenchOption(value="residential", label="住宅地址"),
            WorkbenchOption(value="private", label="私人地址"),
            WorkbenchOption(value="rural_residential", label="偏远住宅"),
        ]
    )
    service_options: list[WorkbenchOption] = Field(
        default_factory=lambda: [
            WorkbenchOption(value="requires_liftgate", label="需要尾板"),
            WorkbenchOption(value="requires_pallet_jack", label="需要手叉车"),
            WorkbenchOption(value="requires_appointment", label="需要预约"),
        ]
    )
    accessorial_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "residential_fee_usd": "住宅附加费",
            "liftgate_fee_usd": "尾板费",
            "pallet_jack_fee_usd": "手叉车费",
            "appointment_fee_usd": "预约费",
            "detention_fee_usd": "等待费",
        }
    )
    backend_risk_tag_labels: dict[str, str] = Field(
        default_factory=lambda: {
            "manual_required": "需要人工确认",
            "zone_not_found": "未命中邮编分区",
            "zone_rule_province_mismatch": "Zone 锚点的邮编省份不一致",
            "zone_price_not_found": "未命中 Zone 价格矩阵",
            "zone_price_disabled": "分区价格已关闭",
            "rural_fsa_secondary_confirmation": "乡村邮编：发价前需二次确认地址和派送条件",
            "city_zone_fallback": "按城市/省份匹配 Zone",
            "city_zone_prefix_family_fallback": "按同邮编族缩小城市 Zone",
            "city_zone_prefix_family_low_support": "同邮编族锚点证据不足",
            "postal_family_fallback": "按同省邮编族模糊匹配 Zone",
            "nearest_postal_prefix_fallback": "采用最近邮编前缀锚点",
            "expected_origin_preferred": "已按省份始发仓过滤旧记录",
            "learned_quote_reused": "复用人工确认学习记录",
            "learned_from_manual_task": "来源为已处理人工任务",
            "hermes_corrective_override": "历史学习规则覆盖",
            "llm_auxiliary_advice": "LLM 辅助建议",
            "llm_auxiliary_zone_matrix": "LLM 建议选择 Zone 价格矩阵",
            "llm_auxiliary_manual_history": "LLM 建议参考人工历史",
            "hermes_agent_correction": "历史 LLM 辅助建议",
            "hermes_agent_zone_matrix": "历史 LLM 建议选择 Zone 价格矩阵",
            "hermes_agent_manual_history": "历史 LLM 建议复用人工历史",
            "billing_pallets_manual_required": "计费托数需人工确认",
            "long_piece_count_suspicious": "超长件数量异常",
            "stale_origin_overridden": "始发仓已按省份规则覆盖",
            "origin_matrix_mismatch": "始发仓与 Zone 价格矩阵冲突",
            "split_record_conflict": "邮编存在拆分记录冲突",
        }
    )
    provinces: list[ProvinceAlias] = Field(default_factory=lambda: _default_provinces())
    parser: WorkbenchParserConfig = Field(default_factory=WorkbenchParserConfig)
    defaults: WorkbenchQuoteDefaults = Field(default_factory=WorkbenchQuoteDefaults)
    risks: WorkbenchRiskConfig = Field(default_factory=WorkbenchRiskConfig)
    copy_template: WorkbenchCopyTemplateConfig = Field(default_factory=WorkbenchCopyTemplateConfig)
    zone_pricing: ZonePricingConfig = Field(default_factory=ZonePricingConfig)


def _default_provinces() -> list[ProvinceAlias]:
    return [
        ProvinceAlias(code="AB", name="Alberta", aliases=["AB", "Alberta", "阿尔伯塔"]),
        ProvinceAlias(code="BC", name="British Columbia", aliases=["BC", "British Columbia", "B.C.", "卑诗", "不列颠哥伦比亚"]),
        ProvinceAlias(code="MB", name="Manitoba", aliases=["MB", "Manitoba", "曼尼托巴"]),
        ProvinceAlias(code="NB", name="New Brunswick", aliases=["NB", "New Brunswick", "新不伦瑞克"]),
        ProvinceAlias(code="NL", name="Newfoundland and Labrador", aliases=["NL", "Newfoundland", "Labrador"]),
        ProvinceAlias(code="NS", name="Nova Scotia", aliases=["NS", "Nova Scotia", "新斯科舍"]),
        ProvinceAlias(code="NT", name="Northwest Territories", aliases=["NT", "Northwest Territories"]),
        ProvinceAlias(code="NU", name="Nunavut", aliases=["NU", "Nunavut"]),
        ProvinceAlias(code="ON", name="Ontario", aliases=["ON", "Ontario", "安大略"]),
        ProvinceAlias(code="PE", name="Prince Edward Island", aliases=["PE", "PEI", "Prince Edward Island"]),
        ProvinceAlias(code="QC", name="Quebec", aliases=["QC", "Quebec", "Québec", "魁北克"]),
        ProvinceAlias(code="SK", name="Saskatchewan", aliases=["SK", "Saskatchewan", "萨省"]),
        ProvinceAlias(code="YT", name="Yukon", aliases=["YT", "Yukon"]),
    ]
