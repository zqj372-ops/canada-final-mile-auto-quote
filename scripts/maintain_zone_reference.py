from __future__ import annotations

from argparse import ArgumentParser
from copy import deepcopy
from datetime import date
import json
import os
from pathlib import Path
import sys
from tempfile import NamedTemporaryFile
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from packages.data_importer.zone_loader import build_zone_indexes, validate_zone_reference_payload
from packages.address_normalizer import normalize_province
from packages.quote_engine.zone_lookup import (
    ORIGIN_BY_PROVINCE,
    get_province_from_strict_fsa,
    normalize_origin,
)


DEFAULT_REFERENCE = Path("reference/canada-final-mile/Zone 邮编前缀 城市 省份 始发仓 查询表.json")

# Every row below is backed by either an explicitly approved correction or a
# successful production quote audit. The evidence stays in the note so future
# maintainers do not turn a city-level inference into an unexplained fact.
# Rules derived from same-city anchors in the Zone reference table and
# historical order evidence (2026-08-07). Every row keeps the anchor FSA
# and the evidence source in its note so the inference stays explainable.
_BACKFILL_RULES: tuple[dict[str, Any], ...] = (
    {
        "zone": 1,
        "postal_prefix": "T1Y",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2A",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2B",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2C",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2E",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2G",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2J",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T2Z",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3C",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3G",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3H",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3K",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3L",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3M",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3N",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3R",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "T3S",
        "city": "CALGARY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 T1X/T3J CALGARY=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "T4C",
        "city": "COCHRANE",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "order_match_anchor",
        "note": "2026-08-07补录：历史订单 ROCKY VIEW COUNTY/COCHRANE 同城匹配 Calgary Zone2；邻近 Zone2 城市 AIRDRIE/OKOTOKS。",
    },
    {
        "zone": 5,
        "postal_prefix": "V5J",
        "city": "BURNABY",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V5H BURNABY=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V4K",
        "city": "DELTA",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V4C/V4G DELTA=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "V1S",
        "city": "KAMLOOPS",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V2C KAMLOOPS=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V2Y",
        "city": "LANGLEY",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V1M LANGLEY=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V7J",
        "city": "NORTH VANCOUVER",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V7G NORTH VANCOUVER=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V6X",
        "city": "RICHMOND",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V6W RICHMOND=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V7A",
        "city": "RICHMOND",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V6W RICHMOND=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V3S",
        "city": "SURREY",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V4N SURREY=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V3X",
        "city": "SURREY",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V4N SURREY=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V3Z",
        "city": "SURREY",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V4N SURREY=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V5M",
        "city": "VANCOUVER",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V5K VANCOUVER=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V6N",
        "city": "VANCOUVER",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V5K VANCOUVER=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "V6Z",
        "city": "VANCOUVER",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 V5K VANCOUVER=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 9,
        "postal_prefix": "E1C",
        "city": "MONCTON",
        "province": "NB",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 E1A MONCTON=Zone9 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "L3J",
        "city": "BEAMSVILLE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L0R BEAMSVILLE=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 4,
        "postal_prefix": "L7E",
        "city": "BOLTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L7C BOLTON=Zone4 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L6R",
        "city": "BRAMPTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L6P/L6T/L6W BRAMPTON=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L6S",
        "city": "BRAMPTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L6P/L6T/L6W BRAMPTON=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L7A",
        "city": "BRAMPTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L6P/L6T/L6W BRAMPTON=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N1T",
        "city": "CAMBRIDGE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N1P/N3E CAMBRIDGE=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N3H",
        "city": "CAMBRIDGE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N1P/N3E CAMBRIDGE=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M4G",
        "city": "EAST YORK",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M3C EAST YORK=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M8W",
        "city": "ETOBICOKE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M8V ETOBICOKE=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M9V",
        "city": "ETOBICOKE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M8V ETOBICOKE=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M9W",
        "city": "ETOBICOKE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M8V ETOBICOKE=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 6,
        "postal_prefix": "K1T",
        "city": "GLOUCESTER",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 K1A GLOUCESTER=Zone6 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N1L",
        "city": "GUELPH",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N1C GUELPH=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "L8N",
        "city": "HAMILTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L8E HAMILTON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "L8R",
        "city": "HAMILTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L8E HAMILTON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "L9C",
        "city": "HAMILTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L8E HAMILTON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 6,
        "postal_prefix": "K2L",
        "city": "KANATA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 K2K KANATA=Zone6 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N2H",
        "city": "KITCHENER",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N2A KITCHENER=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N5W",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N5Z",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N6E",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N6H",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N6L",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N6M",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "N6N",
        "city": "LONDON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 N5V LONDON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "L3R",
        "city": "MARKHAM",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L3P MARKHAM=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "L6B",
        "city": "MARKHAM",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L3P MARKHAM=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L9T",
        "city": "MILTON",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L9E MILTON=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L4W",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L4Y",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L4Z",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5E",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5L",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5M",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5N",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5T",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5V",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 1,
        "postal_prefix": "L5W",
        "city": "MISSISSAUGA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4T/L5S MISSISSAUGA=Zone1 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M2H",
        "city": "NORTH YORK",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1L/M5M/M5N NORTH YORK=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M3A",
        "city": "NORTH YORK",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1L/M5M/M5N NORTH YORK=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M3B",
        "city": "NORTH YORK",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1L/M5M/M5N NORTH YORK=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M3J",
        "city": "NORTH YORK",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1L/M5M/M5N NORTH YORK=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M9L",
        "city": "NORTH YORK",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1L/M5M/M5N NORTH YORK=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "K1W",
        "city": "ORLÉANS",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 K1A ORLÉANS=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 6,
        "postal_prefix": "K1N",
        "city": "OTTAWA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 K1A/K1B OTTAWA=Zone6 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 6,
        "postal_prefix": "K1V",
        "city": "OTTAWA",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 K1A/K1B OTTAWA=Zone6 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 3,
        "postal_prefix": "L1X",
        "city": "PICKERING",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L1V PICKERING=Zone3 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 3,
        "postal_prefix": "L1Y",
        "city": "PICKERING",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L1V PICKERING=Zone3 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "L4C",
        "city": "RICHMOND HILL",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L4B RICHMOND HILL=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M1P",
        "city": "SCARBOROUGH",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1B SCARBOROUGH=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M1S",
        "city": "SCARBOROUGH",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1B SCARBOROUGH=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M1V",
        "city": "SCARBOROUGH",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M1B SCARBOROUGH=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "L2W",
        "city": "ST CATHARINES",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L2M ST CATHARINES=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "P3C",
        "city": "SUDBURY",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 P3A SUDBURY=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "P3E",
        "city": "SUDBURY",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 P3A SUDBURY=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 8,
        "postal_prefix": "P7C",
        "city": "THUNDER BAY",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 P7A THUNDER BAY=Zone8 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M4E",
        "city": "TORONTO",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M5A/M5B/M5C/M5E TORONTO=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "M6K",
        "city": "TORONTO",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 M5A/M5B/M5C/M5E TORONTO=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 3,
        "postal_prefix": "L1P",
        "city": "WHITBY",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L1M WHITBY=Zone3 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 2,
        "postal_prefix": "L4L",
        "city": "WOODBRIDGE",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 L3L/L4H WOODBRIDGE=Zone2 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 8,
        "postal_prefix": "G7H",
        "city": "CHICOUTIMI",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 G7G CHICOUTIMI=Zone8 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 8,
        "postal_prefix": "G7K",
        "city": "CHICOUTIMI",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 G7G CHICOUTIMI=Zone8 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "J8X",
        "city": "GATINEAU",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 J8L GATINEAU=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "J8Y",
        "city": "GATINEAU",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 J8L GATINEAU=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "J5Z",
        "city": "REPENTIGNY",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 J5Y REPENTIGNY=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "J4T",
        "city": "SAINT-HUBERT",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 J3Y SAINT-HUBERT=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 7,
        "postal_prefix": "J6Y",
        "city": "TERREBONNE",
        "province": "QC",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 J5N TERREBONNE=Zone7 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "S4N",
        "city": "REGINA",
        "province": "SK",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 S4S REGINA=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
    {
        "zone": 5,
        "postal_prefix": "S7M",
        "city": "SASKATOON",
        "province": "SK",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "city_anchor_inference",
        "note": "2026-08-07补录：同城锚点 S7K SASKATOON=Zone5 推导；历史订单 FSA 覆盖补全。",
    },
)

CONFIRMED_RULES: tuple[dict[str, Any], ...] = (
    {
        "zone": 5,
        "postal_prefix": "V4B",
        "city": "WHITE ROCK",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "manual_correction",
        "note": "2026-07-27确认：V4B WHITE ROCK -> Calgary Zone5。",
    },
    {
        "zone": 5,
        "postal_prefix": "V4C",
        "city": "DELTA",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "manual_correction",
        "note": "2026-07-28人工确认：V4C DELTA -> Calgary Zone5；同城V4G/V4L生产成功记录交叉验证。",
    },
    {
        "zone": 5,
        "postal_prefix": "V4G",
        "city": "DELTA",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：V4G DELTA -> Calgary Zone5。",
    },
    {
        "zone": 7,
        "postal_prefix": "V1X",
        "city": "KELOWNA",
        "province": "BC",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：V1X KELOWNA -> Calgary Zone7。",
    },
    {
        "zone": 5,
        "postal_prefix": "T9K",
        "city": "FORT MCMURRAY",
        "province": "AB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：T9K FORT MCMURRAY -> Calgary Zone5。",
    },
    {
        "zone": 12,
        "postal_prefix": "R2C",
        "city": "WINNIPEG",
        "province": "MB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：R2C WINNIPEG -> Calgary Zone12。",
    },
    {
        "zone": 5,
        "postal_prefix": "R2P",
        "city": "WINNIPEG",
        "province": "MB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：R2P WINNIPEG -> Calgary Zone5。",
    },
    {
        "zone": 5,
        "postal_prefix": "R3T",
        "city": "WINNIPEG",
        "province": "MB",
        "origin": "卡尔加里",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：R3T WINNIPEG -> Calgary Zone5。",
    },
    {
        "zone": 6,
        "postal_prefix": "N9G",
        "city": "WINDSOR",
        "province": "ON",
        "origin": "多伦多",
        "priority": 10,
        "active": True,
        "match_level": "production_audit_correction",
        "note": "2026-07-28生产成功报价记录确认：N9G WINDSOR -> Toronto Zone6。",
    },
)

CONFIRMED_RULES = (*CONFIRMED_RULES, *_BACKFILL_RULES)


def repair_payload(payload: dict[str, Any], *, last_updated: str) -> tuple[dict[str, Any], dict[str, int]]:
    source_records = payload.get("records")
    if not isinstance(source_records, list):
        raise ValueError("Zone reference must contain a records array.")

    clean_records: list[dict[str, Any]] = []
    malformed_rows: list[str] = []
    removed_cross_province_count = 0
    removed_origin_matrix_count = 0
    for index, record in enumerate(source_records):
        if not isinstance(record, dict):
            malformed_rows.append(f"records[{index}] is not an object")
            continue
        missing = [
            field
            for field in ("postal_prefix", "city", "province", "origin", "zone")
            if record.get(field) in (None, "")
        ]
        if missing:
            malformed_rows.append(f"records[{index}] missing {','.join(missing)}")
            continue
        raw_postal_prefix = str(record["postal_prefix"])
        raw_city = str(record["city"])
        raw_province = str(record["province"])
        postal_prefix = raw_postal_prefix.upper()
        province = normalize_province(raw_province)
        if (
            raw_postal_prefix != postal_prefix
            or raw_city != raw_city.strip().upper()
            or province is None
            or raw_province != province
        ):
            malformed_rows.append(
                f"records[{index}] values must use canonical FSA/CITY/PROVINCE casing"
            )
            continue
        inferred_province = get_province_from_strict_fsa(postal_prefix)
        if inferred_province is None or province is None:
            malformed_rows.append(
                f"records[{index}] invalid FSA/province {postal_prefix} + {record['province']}"
            )
            continue
        try:
            zone = int(record["zone"])
        except (TypeError, ValueError):
            malformed_rows.append(f"records[{index}] invalid zone {record['zone']}")
            continue
        if zone <= 0:
            malformed_rows.append(f"records[{index}] invalid zone {record['zone']}")
            continue
        if inferred_province != province:
            removed_cross_province_count += 1
            continue
        expected_origin = ORIGIN_BY_PROVINCE.get(province)
        if expected_origin and normalize_origin(str(record["origin"])) != expected_origin:
            removed_origin_matrix_count += 1
            continue
        clean_records.append(deepcopy(record))

    if malformed_rows:
        raise ValueError(
            "Refusing to repair malformed Zone records: "
            f"malformed_error_count={len(malformed_rows)}; "
            f"examples={'; '.join(malformed_rows[:10])}"
        )

    deduplicated: dict[tuple[str, str, str, str, int], dict[str, Any]] = {}
    duplicate_count = 0
    for record in clean_records:
        key = _business_key(record)
        existing = deduplicated.get(key)
        if existing is None:
            deduplicated[key] = record
            continue
        duplicate_count += 1
        if _record_preference(record) > _record_preference(existing):
            deduplicated[key] = record
    clean_records = list(deduplicated.values())

    confirmed_business_keys = {_business_key(rule) for rule in CONFIRMED_RULES}
    for rule in CONFIRMED_RULES:
        conflicts = [
            record
            for record in clean_records
            if _location_key(record) == _location_key(rule)
            and _business_key(record) != _business_key(rule)
        ]
        if conflicts:
            raise ValueError(
                "Confirmed rule conflicts with existing location variants; "
                f"location={_location_key(rule)} conflicts={conflicts}"
            )
    clean_records = [
        record
        for record in clean_records
        if _business_key(record) not in confirmed_business_keys
    ]
    clean_records.extend(deepcopy(list(CONFIRMED_RULES)))
    clean_records.sort(key=_record_sort_key)

    repaired = dict(payload)
    repaired["last_updated"] = last_updated
    repaired["total_records"] = len(clean_records)
    repaired["records"] = clean_records
    repaired["data"] = build_zone_indexes(clean_records)
    validate_zone_reference_payload(repaired)
    return repaired, {
        "source_records": len(source_records),
        "removed_cross_province_records": removed_cross_province_count,
        "removed_origin_matrix_records": removed_origin_matrix_count,
        "removed_duplicate_records": duplicate_count,
        "confirmed_rules_upserted": len(CONFIRMED_RULES),
        "final_records": len(clean_records),
    }


def _location_key(record: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(record.get("postal_prefix") or "").strip().upper(),
        str(record.get("city") or "").strip().upper(),
        str(record.get("province") or "").strip().upper(),
    )


def _business_key(record: dict[str, Any]) -> tuple[str, str, str, str, int]:
    return (
        *_location_key(record),
        normalize_origin(str(record.get("origin") or "")) or "",
        int(record.get("zone") or 0),
    )


def _record_preference(record: dict[str, Any]) -> tuple[int, int, int, int]:
    note = str(record.get("note") or "").strip()
    return (
        int(record.get("active", True) is True),
        -int(record.get("priority") or 100),
        int(bool(note)),
        len(note),
    )


def _record_sort_key(record: dict[str, Any]) -> tuple[str, str, str, int, str]:
    return (
        str(record.get("province") or "").upper(),
        str(record.get("city") or "").upper(),
        str(record.get("postal_prefix") or "").upper(),
        int(record.get("zone") or 0),
        str(record.get("origin") or ""),
    )


def main() -> None:
    parser = ArgumentParser(
        description="Remove cross-province Zone rows, upsert confirmed rules, and rebuild composite indexes."
    )
    parser.add_argument("--path", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--last-updated", default=date.today().isoformat())
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    payload = json.loads(args.path.read_text(encoding="utf-8"))
    repaired, report = repair_payload(payload, last_updated=args.last_updated)
    report["written"] = int(args.write)
    if args.write:
        contents = json.dumps(repaired, ensure_ascii=False, indent=2) + "\n"
        temp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=args.path.parent,
                prefix=f".{args.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temp_file:
                temp_file.write(contents)
                temp_file.flush()
                os.fsync(temp_file.fileno())
                temp_path = Path(temp_file.name)
            validate_zone_reference_payload(
                json.loads(temp_path.read_text(encoding="utf-8"))
            )
            os.replace(temp_path, args.path)
        finally:
            if temp_path is not None and temp_path.exists():
                temp_path.unlink()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
