export const FCL_CUSTOMER_TYPES: Record<string, string> = {
  importer: "进口商",
  exporter: "出口商",
  platform_seller: "平台卖家",
  forwarder: "货代同行",
  warehouse: "仓库",
  other: "其他",
};

export const FCL_SPECIAL_ATTRIBUTES: Record<string, string> = {
  general_cargo: "普货",
  battery: "带电",
  magnetic: "带磁",
  liquid: "液体",
  powder: "粉末",
  food: "食品",
  wood: "木制品",
  dangerous_goods: "危险品",
  branded: "品牌",
  reefer: "冷藏",
  oversized: "超尺寸",
};

export const FCL_SERVICE_STAGES: Record<string, string> = {
  pickup: "提货",
  ocean: "海运",
  customs: "清关",
  warehousing: "仓储",
  delivery: "派送",
  door_to_door: "全程",
};

export const FCL_TRADE_TERMS: Record<string, string> = {
  EXW: "EXW",
  FOB: "FOB",
  CFR: "CFR",
  CIF: "CIF",
  DAP: "DAP",
  DDP: "DDP",
  OTHER: "其他",
};

export const FCL_EXPORT_DECLARATIONS: Record<string, string> = {
  customer: "客户可报关",
  platform: "需平台安排",
  pending: "待确认",
};

export const FCL_IMPORTER_EXISTS: Record<string, string> = {
  yes: "是",
  no: "否",
  unknown: "不确定",
};

export const FCL_TAX_INCLUDED: Record<string, string> = {
  yes: "是（包税）",
  no: "否（自税）",
  compare: "需要比较",
};

export const FCL_PRIORITY_GOALS: Record<string, string> = {
  economy: "经济",
  speed: "时效",
  stable: "稳定",
  balanced: "平衡",
};

export const FCL_DEADLINE_STRICTNESS: Record<string, string> = {
  hard: "硬性",
  negotiable: "可协商",
  reference: "仅参考",
};

export const FCL_ADDRESS_TYPES: Record<string, string> = {
  commercial: "商业",
  residential: "住宅",
  amazon: "Amazon",
  warehouse: "仓库",
};

export const FCL_WOOD_PACKAGING: Record<string, string> = {
  none: "无木",
  compliant: "合规木包装",
  unknown: "待确认",
};

export const FCL_BN_RM_STATUSES: Record<string, string> = {
  ready: "齐备",
  applying: "申请中",
  none: "无",
  unknown: "不清楚",
};

export const FCL_CARM_STATUSES: Record<string, string> = {
  ready: "齐备",
  pending: "待授权",
  unknown: "不清楚",
};

export const FCL_BROKER_OPTIONS: Record<string, string> = {
  yes: "有",
  need_platform: "需平台安排",
};

export const FCL_YES_NO_UNKNOWN: Record<string, string> = {
  yes: "是",
  no: "否",
  unknown: "不确定",
};

export const FCL_REQUIRED_FIELD_LABELS: Record<string, string> = {
  customer_name: "客户/公司名称",
  contact: "联系人及联系方式",
  customer_type: "客户类型",
  pol: "起运港 POL",
  pod: "目的港 POD",
  destination_postal_code: "目的邮编（到门）",
  destination_address: "完整收货地址（到门）",
  containers: "柜型柜量",
  cargo: "货物数据（品名/件数/毛重/体积）",
  cargo_name: "货名",
  cargo_value: "货值",
  cargo_value_currency: "货值币种",
  hs_code: "HS 编码",
  origin_country: "原产地",
  stackable: "可否叠放",
  special_attributes: "特殊属性",
  sds_un_info: "SDS/UN/电池资料",
  wood_packaging: "木质包装/IPPC",
  ready_date: "预计出货/备货日期",
  target_etd: "目标 ETD",
  expected_delivery_date: "期望到门日期",
  deadline_strictness: "时限性质",
  acceptable_transit_days: "可接受中转天数",
  trade_terms: "贸易条款",
  export_declaration: "中国出口报关能力",
  importer_exists: "是否有加拿大进口商",
  importer_legal_name: "进口商法定名称",
  bn_rm_status: "BN/RM 账号状态",
  carm_status: "CARM/报关授权",
  has_broker: "是否已有报关行",
  service_scope: "交付范围",
  service_stages: "服务环节",
  tax_included: "是否包税",
  priority_goal: "优先目标",
  address_type: "地址类型",
  tail_lift: "尾板需求",
  appointment_window: "预约时间窗",
  forklift: "叉车/装卸平台",
  platform_warehouse: "平台仓资料",
  declaration_acknowledged: "如实申报确认",
};

export function labelOf(map: Record<string, string>, value: string | null | undefined): string {
  return value ? (map[value] ?? value) : "—";
}

export function optionList(map: Record<string, string>): Array<{ value: string; label: string }> {
  return Object.entries(map).map(([value, label]) => ({ value, label }));
}
