"""Local mock OpenAI-compatible endpoint for QuotePage development.

Serves deterministic cargo/address extraction JSON so the full quote
pipeline (extract -> zone lookup -> pricing -> result modal) can be
exercised locally without a real model key.

Supported inquiry formats (mirrors the real-world corpus in
tests/ai-assistant/test_quote_extractor.py):

- Aggregate rows: "NO. OF PACKAGES: 18 / TOTAL GROSS WT: 1,234.5 KGS /
  VOLUME: 12.75 CBM", "20箱，单箱毛重55公斤，共计3.84方",
  "QTY 12 PKGS; GW 1250,5 KG; VOL 8,75 CBM" (European decimal comma)
- Line-by-line dimensions: "60x36x50cm/68kg*4", "3.21*0.27*0.25m*38kg*4"
  (meters), "W:80cm H:150cm L:120cm, QTY 2", "96x120x70cm 115kg每件 共3件"
- Packaging: 木箱/crates, 编织袋/woven bag, 托盘/pallet, 纸箱/carton
- Explicit pallets: "5托" / "5 pallets"; overlength: "X件长件"
- Addresses: "6155 rue LaFontaine h1n2b8 Montreal QC Canada",
  "27 Arthur Griffin Crescent，Caledon East, Ontario, Canada，L7C 4E9"

Run:  python3 scripts/dev_mock_ai_server.py  (listens on 127.0.0.1:9999)
"""
from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

POSTAL_RE = re.compile(
    r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTVWXYZ]\s?\d[ABCEGHJ-NPRSTVWXYZ]\d)\b", re.I
)
# 数字: 千分位(1,234.5 或 1,234) / 欧式逗号小数(1250,5 / 8,75) / 普通小数
NUMBER = r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
NUM_RE = re.compile(NUMBER)

DIM_LINE_RE = re.compile(
    rf"([A-Za-z]*(?:[xX×*])\s*{NUMBER}\s*(?:[xX×*])\s*{NUMBER}\s*(?:[xX×*])\s*{NUMBER})\s*(cm|mm|m|in|inch|英寸)?",
    re.I,
)
DIM_TRIPLE_RE = re.compile(rf"({NUMBER})\s*(?:[xX×*])\s*({NUMBER})\s*(?:[xX×*])\s*({NUMBER})", re.I)

KG_UNITS = r"(?:kg|kgs|kg\.|kilograms?|公斤|千克|克)"
TON_UNITS = r"(?:mt|吨|tonnes?|tons?)"
LB_UNITS = r"(?:lbs?|lb\.|pounds?|磅)"
CBM_UNITS = r"(?:cbm|m3|m³|立方米|立方|方)"
CFT_UNITS = r"(?:cu\.?\s*ft|cft|立方英尺)"
PIECE_UNITS = r"(?:件|箱|pcs|pieces?|pkgs?|packages?|cartons?|units?)"

# 聚合: 数字 + 单位(后置)或 关键词 + 数字(前置), 单位词同时充当分隔
AGG_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "piece_count": [
        re.compile(rf"({NUMBER})\s*(?:{PIECE_UNITS})(?![A-Za-z0-9])", re.I),
        re.compile(rf"(?:no\.?\s*of\s*packages?|qty|quantity|数量|件数|箱数)\s*[:：]?\s*({NUMBER})", re.I),
        re.compile(rf"共\s*({NUMBER})\s*(?:{PIECE_UNITS})?", re.I),
    ],
    "weight_kg": [
        re.compile(rf"({NUMBER})\s*(?:{KG_UNITS})(?![A-Za-z0-9])", re.I),
        re.compile(rf"({NUMBER})\s*(?:{LB_UNITS})(?![A-Za-z0-9])", re.I),
        re.compile(rf"({NUMBER})\s*(?:{TON_UNITS})(?![A-Za-z0-9])", re.I),
        re.compile(rf"(?:重量|毛重|总重|g\.?w\.?|gross\s*weight|wt|weight)\s*[:：=]?\s*({NUMBER})\s*(?:{KG_UNITS}|{LB_UNITS}|{TON_UNITS})?", re.I),
    ],
    "cbm": [
        re.compile(rf"({NUMBER})\s*(?:{CBM_UNITS})(?![A-Za-z0-9])", re.I),
        re.compile(rf"({NUMBER})\s*(?:{CFT_UNITS})(?![A-Za-z0-9])", re.I),
        re.compile(rf"(?:体积|容积|总方|volume|vol|meas)\s*[:：=]?\s*({NUMBER})\s*(?:{CBM_UNITS}|{CFT_UNITS})?", re.I),
    ],
    "explicit_pallet_count": [
        re.compile(rf"({NUMBER})\s*(?:托|托盘|pallets?)(?![A-Za-z0-9])", re.I),
        re.compile(rf"(?:托盘|pallets?)\s*[:：]?\s*({NUMBER})", re.I),
    ],
    "long_piece_count": [
        re.compile(rf"({NUMBER})\s*(?:件|个)?\s*(?:长件|long\s*pieces?)\b", re.I),
    ],
}

# 行内: 重量×数量片段 (移除后再解析尺寸)
WT_QTY_STRIP_RE = re.compile(
    rf"({NUMBER})\s*(?:{KG_UNITS}|{LB_UNITS})\s*[*@]\s*({NUMBER})", re.I
)
# 行尾数量: *N / @N / 共N件 / QTY N
LINE_QTY_RE = re.compile(r"(?:qty|quantity|数量)\s*[:：]?\s*(\d+)|[*@]\s*(\d+)\s*$|共\s*(\d+)\s*(?:件)?", re.I)
LINE_WEIGHT_RE = re.compile(rf"({NUMBER})\s*((?:{KG_UNITS})|(?:{LB_UNITS}))", re.I)

PROVINCE_MAP = {
    "AB": "AB", "ALBERTA": "AB", "阿尔伯塔": "AB",
    "BC": "BC", "BRITISH COLUMBIA": "BC", "卑诗": "BC",
    "MB": "MB", "MANITOBA": "MB", "马尼托巴": "MB",
    "NB": "NB", "NEW BRUNSWICK": "NB", "新不伦瑞克": "NB",
    "NL": "NL", "NEWFOUNDLAND": "NL", "纽芬兰": "NL",
    "NS": "NS", "NOVA SCOTIA": "NS", "新斯科舍": "NS",
    "ON": "ON", "ONTARIO": "ON", "安大略": "ON",
    "PE": "PE", "PRINCE EDWARD ISLAND": "PE", "爱德华王子岛": "PE",
    "QC": "QC", "QUEBEC": "QC", "QUÉBEC": "QC", "魁北克": "QC",
    "SK": "SK", "SASKATCHEWAN": "SK", "萨斯喀彻温": "SK",
}
PROVINCE_WORDS = set(PROVINCE_MAP) | {"CANADA", "加拿大"}
PACKAGING_HINTS = [
    ("编织袋", "woven_bag"), ("柔性包装", "flexible_packaging"),
    ("woven", "woven_bag"), ("flexible", "flexible_packaging"),
    ("木箱", "wooden_crate"), ("crate", "wooden_crate"),
    ("托盘", "pallet"), ("pallet", "pallet"),
    ("纸箱", "carton"), ("carton", "carton"),
]


def _to_float(text: str) -> float | None:
    text = text.strip().replace(" ", "")
    if not text:
        return None
    if "," in text and "." in text:
        text = text.replace(",", "")
    elif "," in text and text.count(",") == 1:
        left, right = text.split(",", 1)
        if right.isdigit() and len(right) == 3:
            text = left + right  # 千分位: 1,234 -> 1234
        else:
            text = text.replace(",", ".")  # 欧式小数: 1250,5 -> 1250.5
    elif "," in text:
        text = text.replace(",", "")
    try:
        value = float(text)
        return value if value > 0 else None
    except ValueError:
        return None


def _dim_to_cm(value: float, unit: str | None) -> float:
    if unit is None:
        return value
    unit = unit.lower()
    if unit == "m":
        return value * 100
    if unit == "mm":
        return value / 10
    if unit in ("in", "inch", "英寸"):
        return value * 2.54
    return value  # cm


def _weight_to_kg(value: float, unit: str | None) -> float:
    if unit is None:
        return value
    unit = unit.lower().replace(".", "")
    if unit in ("lbs", "lb", "pounds", "磅"):
        return value * 0.453592
    if unit in ("mt", "吨", "tonnes", "tonne", "tons", "ton"):
        return value * 1000
    if unit in ("克",):
        return value / 1000
    return value  # kg/kgs/公斤/千克


def _agg(text: str, key: str) -> float | int | None:
    """Extract the first aggregate value for a key with pattern priority."""
    for pattern in AGG_PATTERNS[key]:
        match = pattern.search(text)
        if match:
            value = _to_float(match.group(1))
            if value is not None:
                return int(value) if key in ("piece_count", "explicit_pallet_count", "long_piece_count") else round(value, 3)
    return None


def _explicit_total_weight(text: str) -> float | None:
    """总重/毛重/GW/weight 关键词后的重量。

    跳过"总重：1.3cbm 737kg"里的体积数字, 以及"单箱毛重55公斤"这类
    单箱(非总重)表述。
    """
    marker = re.compile(r"(?:总重|总毛重|重量|毛重|g\.?w\.?|gross\s*weight|wt|weight|总)\s*[:：=]?\s*", re.I)
    for match in marker.finditer(text):
        before = text[: match.start()]
        if re.search(r"(?:单箱|每箱|每件|each)\s*$", before, re.I):
            continue  # 单箱毛重, 不是总重
        rest = text[match.end():]
        for number in NUM_RE.finditer(rest):
            value = _to_float(number.group(0))
            if value is None:
                continue
            after = rest[number.end():]
            if re.match(r"\s*(?:cbm|m3|m³|方|立方米|cu\.?\s*ft|cft)", after, re.I):
                continue  # 这是体积数字
            unit = re.match(r"\s*((?:{KG_UNITS})|(?:{LB_UNITS})|(?:{TON_UNITS}))", after, re.I)
            unit_text = unit.group(1) if unit else None
            return _weight_to_kg(value, unit_text)
    return None


def parse_cargo_rows(user: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in user.splitlines():
        stripped = line.strip()
        # "重量*数量" 片段(如 68kg*4): 提取 (weight, qty), 并从行中移除避免干扰尺寸解析
        stripped_wq = WT_QTY_STRIP_RE.sub(" ", stripped)
        wq_match = WT_QTY_STRIP_RE.search(stripped)
        triple = DIM_TRIPLE_RE.search(stripped_wq)
        if not triple:
            continue
        dims = [_to_float(g) for g in triple.groups()]
        if not all(dims):
            continue
        after = stripped_wq[triple.end():]
        unit_match = re.match(r"\s*(cm|mm|m|in|inch|英寸)", after, re.I)
        unit = unit_match.group(1) if unit_match else None
        dims = sorted((_dim_to_cm(d, unit) for d in dims), reverse=True)
        tail = stripped_wq[triple.end():]
        quantity = 1
        qty_match = LINE_QTY_RE.search(tail)
        if qty_match:
            quantity = int(qty_match.group(1) or qty_match.group(2) or qty_match.group(3) or 1)
        weight = None
        weight_match = LINE_WEIGHT_RE.search(tail)
        if weight_match:
            weight = _weight_to_kg(_to_float(weight_match.group(1)) or 0, weight_match.group(2))
        if weight is None and wq_match:
            weight = _weight_to_kg(_to_float(wq_match.group(1)) or 0, None)
        if quantity == 1 and wq_match:
            quantity = int(wq_match.group(2))
        rows.append({
            "quantity": quantity,
            "length_cm": round(dims[0], 1),
            "width_cm": round(dims[1], 1),
            "height_cm": round(dims[2], 1),
            "weight_kg": round(weight, 2) if weight else None,
            "cbm": None,
            "contained_customer_pieces": quantity,
            "source_span": f"mock:line{stripped[:60]}",
        })
    aggregates: dict[str, Any] = {}
    for key in ("piece_count", "cbm", "explicit_pallet_count", "long_piece_count"):
        aggregates[key] = _agg(user, key)
    # 重量: 显式总重关键词 > 行汇总 > 泛匹配
    aggregates["weight_kg"] = _explicit_total_weight(user)
    if aggregates["weight_kg"] is None and rows and all(row["weight_kg"] for row in rows):
        aggregates["weight_kg"] = round(sum(row["weight_kg"] * row["quantity"] for row in rows), 1)
    if aggregates["weight_kg"] is None and aggregates["piece_count"]:
        # 单箱毛重 × 件数: "20箱，单箱毛重55公斤" -> 1100kg
        per_unit = re.search(
            rf"(?:单箱|每箱|每件|each)\s*(?:毛重|重|weight|wt)?\s*[:：]?\s*({NUMBER})\s*(?:{KG_UNITS}|{LB_UNITS})", user, re.I
        )
        if per_unit:
            unit_w = _to_float(per_unit.group(1)) or 0
            aggregates["weight_kg"] = round(unit_w * aggregates["piece_count"], 1)
    if aggregates["weight_kg"] is None:
        aggregates["weight_kg"] = _agg(user, "weight_kg")
    return rows, aggregates


def parse_address(user: str) -> dict[str, Any]:
    postal = POSTAL_RE.search(user)
    postal_code = postal.group(1).upper().replace(" ", "") if postal else None
    upper = user.upper()
    province = None
    for key in PROVINCE_MAP:
        if re.search(rf"\b{re.escape(key)}\b", upper):
            province = PROVINCE_MAP[key]
            break
    # 城市: 邮编前的最后一段 (去掉省份/国家/数字段)
    city = None
    if postal:
        before = user[: postal.start()]
        parts = [p.strip().strip("，,;:：") for p in re.split(r"[,，;]", before) if p.strip()]
        for part in reversed(parts):
            if not re.search(r"\d", part) and part.upper() not in PROVINCE_WORDS and len(part) > 1:
                city = part.upper()
                break
        if city is None:
            # 邮编后的 "City ProvinceCode" (如 "h1n2b8 Montreal QC Canada")
            after_postal = user[postal.end():]
            after_tokens = [t.strip("，,;:：") for t in re.split(r"\s+", after_postal) if t.strip()]
            for idx in range(len(after_tokens) - 1):
                if after_tokens[idx + 1].upper() in PROVINCE_MAP and not re.search(r"\d", after_tokens[idx]):
                    city = after_tokens[idx].upper()
                    break
        if city is None:
            # 无逗号: 邮编前的 "City ProvinceCode" 或最后一个不含数字的词
            tokens = [t.strip("，,;:：") for t in re.split(r"\s+", before) if t.strip()]
            for idx in range(len(tokens) - 1, -1, -1):
                token = tokens[idx].upper()
                if re.search(r"\d", token) or token in PROVINCE_WORDS:
                    continue
                if idx + 1 < len(tokens) and tokens[idx + 1].upper() in PROVINCE_MAP:
                    city = token
                elif city is None:
                    city = token
                break
    # 地址行: 含数字且不含货物特征的行; 优先含邮编的行
    address_line = None
    cargo_markers = re.compile(r"(?:CBM|KG|KGS|公斤|方|箱|件|QTY|NO\.|PACKAGES|尺寸|箱规|长件|托)", re.I)
    dim_marker = re.compile(r"\d+(?:[.,]\d+)?\s*(?:[xX×*])\s*\d+", re.I)
    candidates = [ln.strip() for ln in user.splitlines() if re.search(r"\d", ln)]
    for line in candidates:
        if postal and postal_code.replace(" ", "") in line.upper().replace(" ", ""):
            address_line = line
            break
    if address_line is None:
        for line in candidates:
            if cargo_markers.search(line) or dim_marker.search(line):
                continue
            address_line = line
            break
    return {
        "address_line": address_line,
        "postal_code": postal_code,
        "city": city,
        "province": province,
        "country": "Canada",
        "address_type": "commercial",
        "requires_liftgate": bool(re.search(r"(?:尾板|liftgate)", user, re.I)),
        "requires_pallet_jack": bool(re.search(r"(?:手叉车|pallet\s*jack|叉车)", user, re.I)),
        "requires_appointment": bool(re.search(r"(?:预约|appointment)", user, re.I)),
        "detention_minutes": 0,
        "missing_fields": [],
        "confidence": 90,
    }


def parse_cargo(user: str) -> dict[str, Any]:
    rows, aggregates = parse_cargo_rows(user)
    lower = user.lower()
    packaging_type = "carton"
    for hint, value in PACKAGING_HINTS:
        if hint.lower() in lower:
            packaging_type = value
            break
    piece_count = aggregates.get("piece_count")
    weight_kg = aggregates.get("weight_kg")
    cbm = aggregates.get("cbm")
    if piece_count is None and rows:
        piece_count = sum(row["quantity"] for row in rows)
    if weight_kg is None and rows and all(row["weight_kg"] for row in rows):
        weight_kg = round(sum(row["weight_kg"] * row["quantity"] for row in rows), 1)
    if cbm is None and rows and all(row["length_cm"] and row["height_cm"] for row in rows):
        cbm = round(
            sum(row["length_cm"] * row["width_cm"] * row["height_cm"] * row["quantity"] for row in rows) / 1_000_000,
            3,
        )
    if piece_count is None:
        piece_count = 1
    if not rows:
        rows = [{
            "quantity": piece_count,
            "length_cm": None,
            "width_cm": None,
            "height_cm": None,
            "weight_kg": round(weight_kg / piece_count, 2) if weight_kg else None,
            "cbm": round(cbm / piece_count, 4) if cbm else None,
            "contained_customer_pieces": piece_count,
            "source_span": "mock:aggregate-derived",
        }]
    missing = []
    if not POSTAL_RE.search(user):
        missing.append("postal_code")
    return {
        "cbm": cbm,
        "weight_kg": weight_kg,
        "piece_count": piece_count,
        "packaging_type": packaging_type,
        "longest_side_cm": max((row["length_cm"] or 0 for row in rows), default=None) or None,
        "explicit_pallet_count": aggregates.get("explicit_pallet_count"),
        "is_stackable": packaging_type == "woven_bag",
        "cargo_items": rows,
        "missing_fields": missing,
        "confidence": 90,
    }


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            body = {}
        messages = body.get("messages") or []
        user = next((m.get("content", "") for m in reversed(messages) if m.get("role") == "user"), "")
        system = next((m.get("content", "") for m in messages if m.get("role") == "system"), "")
        if "地址" in system or "address" in system.lower():
            payload = parse_address(user)
        else:
            payload = parse_cargo(user)
        response = {
            "choices": [{"message": {"role": "assistant", "content": json.dumps(payload, ensure_ascii=False)}}]
        }
        data = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    HTTPServer(("127.0.0.1", 9999), Handler).serve_forever()
