from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Any

import pandas as pd

from packages.quote_engine.zone_lookup import normalize_origin


MAX_IMPORT_ROWS = 5000


@dataclass(frozen=True)
class SpreadsheetIssue:
    row: int | None
    field: str | None
    message: str

    def to_dict(self) -> dict[str, object]:
        return {"row": self.row, "field": self.field, "message": self.message}


@dataclass
class ZonePriceSpreadsheet:
    source_row_count: int = 0
    rows: list[dict[str, object]] = field(default_factory=list)
    fuel_overrides: dict[str, Decimal] = field(default_factory=dict)
    errors: list[SpreadsheetIssue] = field(default_factory=list)
    warnings: list[SpreadsheetIssue] = field(default_factory=list)

    @property
    def can_import(self) -> bool:
        return not self.errors and bool(self.rows or self.fuel_overrides)


COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "origin": (
        "origin",
        "origin_warehouse",
        "warehouse",
        "始发仓",
        "始发仓库",
        "仓库",
    ),
    "zone": ("zone", "分区", "区域"),
    "billing_pallets": (
        "billing_pallets",
        "billing_pallet",
        "pallets",
        "pallet_count",
        "托数",
        "计费托数",
    ),
    "base_price_usd": (
        "base_price_usd",
        "base_price",
        "price_usd",
        "基础派送费_usd",
        "基础派送费",
        "基础价格",
        "价格",
    ),
    "fuel_percent": (
        "fuel_percent",
        "fuel_surcharge_percent",
        "燃油附加比例",
        "燃油附加比例_%",
        "燃油比例",
        "燃油比例_%",
    ),
    "source": ("source", "source_note", "来源", "来源备注", "备注"),
    "last_updated": (
        "last_updated",
        "updated_date",
        "更新日期",
        "最后更新",
    ),
}


def load_zone_price_spreadsheet(path: Path) -> ZonePriceSpreadsheet:
    frame = _read_frame(path)
    if len(frame.index) > MAX_IMPORT_ROWS:
        raise ValueError(f"表格最多支持 {MAX_IMPORT_ROWS} 行，当前为 {len(frame.index)} 行。")

    canonical_columns, pallet_columns = _resolve_columns(list(frame.columns))
    has_long_pallet = "billing_pallets" in canonical_columns
    has_long_price = "base_price_usd" in canonical_columns

    missing = [key for key in ("origin", "zone") if key not in canonical_columns]
    if missing:
        labels = "、".join(_field_label(field) for field in missing)
        raise ValueError(f"表格缺少必填列：{labels}。")
    if has_long_pallet != has_long_price:
        raise ValueError("明细表必须同时包含“托数”和“基础派送费”两列。")
    if has_long_pallet and pallet_columns:
        raise ValueError("不能同时使用“托数/基础派送费”明细列和“1托、2托…”宽表列。")
    if not has_long_pallet and not pallet_columns:
        raise ValueError("表格需要包含“托数 + 基础派送费”明细列，或至少一个“1托、2托…”价格列。")

    result = ZonePriceSpreadsheet()
    seen_price_keys: dict[tuple[str, int, int], int] = {}
    fuel_rows: dict[str, int] = {}

    for row_number, (_, series) in enumerate(frame.iterrows(), start=2):
        if all(_is_blank(value) for value in series.values):
            continue
        result.source_row_count += 1
        errors_before_row = len(result.errors)

        origin = _parse_origin(series.get(canonical_columns["origin"]), row_number, result.errors)
        zone = _parse_positive_int(
            series.get(canonical_columns["zone"]),
            row_number,
            "zone",
            result.errors,
        )
        source = _optional_text(series.get(canonical_columns.get("source"))) or "spreadsheet-import"
        last_updated = _parse_last_updated(
            series.get(canonical_columns.get("last_updated")),
            row_number,
            result.errors,
        )
        fuel_percent = _parse_optional_decimal(
            series.get(canonical_columns.get("fuel_percent")),
            row_number,
            "fuel_percent",
            result.errors,
        )

        if origin is None or zone is None:
            continue

        fuel_key = f"{origin}|{zone}"
        if fuel_percent is not None:
            existing_fuel = result.fuel_overrides.get(fuel_key)
            if existing_fuel is not None and existing_fuel != fuel_percent:
                result.errors.append(
                    SpreadsheetIssue(
                        row=row_number,
                        field="fuel_percent",
                        message=(
                            f"同一始发仓和 Zone 的燃油比例不一致；第 {fuel_rows[fuel_key]} 行为 "
                            f"{existing_fuel}%，本行为 {fuel_percent}%。"
                        ),
                    )
                )
            else:
                result.fuel_overrides[fuel_key] = fuel_percent
                fuel_rows[fuel_key] = fuel_rows.get(fuel_key, row_number)

        parsed_prices: list[tuple[int, Decimal, str]] = []
        if has_long_pallet:
            billing_pallets = _parse_positive_int(
                series.get(canonical_columns["billing_pallets"]),
                row_number,
                "billing_pallets",
                result.errors,
            )
            base_price = _parse_required_decimal(
                series.get(canonical_columns["base_price_usd"]),
                row_number,
                "base_price_usd",
                result.errors,
            )
            if billing_pallets is not None and base_price is not None:
                parsed_prices.append((billing_pallets, base_price, "base_price_usd"))
        else:
            for pallet_count, column in sorted(pallet_columns.items()):
                raw_price = series.get(column)
                if _is_blank(raw_price):
                    continue
                price = _parse_required_decimal(
                    raw_price,
                    row_number,
                    f"{pallet_count}_pallets",
                    result.errors,
                )
                if price is not None:
                    parsed_prices.append((pallet_count, price, f"{pallet_count}_pallets"))

        if len(result.errors) > errors_before_row:
            continue
        if not parsed_prices and fuel_percent is None:
            result.errors.append(
                SpreadsheetIssue(
                    row=row_number,
                    field=None,
                    message="该行没有可导入的价格或燃油比例。",
                )
            )
            continue

        for billing_pallets, base_price, field_name in parsed_prices:
            price_key = (origin, zone, billing_pallets)
            if price_key in seen_price_keys:
                result.errors.append(
                    SpreadsheetIssue(
                        row=row_number,
                        field=field_name,
                        message=(
                            f"始发仓 {origin}、Zone {zone}、{billing_pallets} 托与第 "
                            f"{seen_price_keys[price_key]} 行重复。"
                        ),
                    )
                )
                continue
            seen_price_keys[price_key] = row_number
            result.rows.append(
                {
                    "row_number": row_number,
                    "origin": origin,
                    "zone": zone,
                    "billing_pallets": billing_pallets,
                    "base_price_usd": base_price,
                    "fuel_percent": fuel_percent,
                    "source": source,
                    "last_updated": last_updated,
                }
            )

    if result.source_row_count == 0:
        result.errors.append(SpreadsheetIssue(row=None, field=None, message="表格中没有数据行。"))
    if not result.rows and not result.fuel_overrides and not result.errors:
        result.errors.append(SpreadsheetIssue(row=None, field=None, message="没有解析到可导入的数据。"))
    if "fuel_percent" not in canonical_columns:
        result.warnings.append(
            SpreadsheetIssue(row=None, field="fuel_percent", message="表格未包含燃油比例列，本次只更新基础派送费。")
        )
    return result


def _read_frame(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    try:
        if suffix == ".csv":
            return pd.read_csv(path, dtype=object, encoding="utf-8-sig")
        if suffix in {".xlsx", ".xls"}:
            return pd.read_excel(path, dtype=object)
    except Exception as exc:
        # Spreadsheet engines raise different exception types for malformed
        # workbooks. Normalize all reader failures into a safe import error.
        raise ValueError(f"无法读取表格：{exc}") from exc
    raise ValueError("仅支持 CSV、XLSX 和 XLS 文件。")


def _resolve_columns(columns: list[object]) -> tuple[dict[str, object], dict[int, object]]:
    alias_to_key = {
        _normalize_header(alias): key
        for key, aliases in COLUMN_ALIASES.items()
        for alias in aliases
    }
    canonical: dict[str, object] = {}
    pallet_columns: dict[int, object] = {}

    for column in columns:
        normalized = _normalize_header(str(column))
        canonical_key = alias_to_key.get(normalized)
        if canonical_key:
            if canonical_key in canonical:
                raise ValueError(f"列“{_field_label(canonical_key)}”重复。")
            canonical[canonical_key] = column
            continue
        pallet_count = _extract_pallet_count(normalized)
        if pallet_count is None:
            continue
        if pallet_count in pallet_columns:
            raise ValueError(f"{pallet_count} 托价格列重复。")
        pallet_columns[pallet_count] = column
    return canonical, pallet_columns


def _normalize_header(value: str) -> str:
    normalized = value.strip().lstrip("\ufeff").lower()
    normalized = normalized.replace("%", " percent ").replace("％", " percent ")
    normalized = re.sub(r"[\s\-./\\（）()]+", "_", normalized)
    return re.sub(r"_+", "_", normalized).strip("_")


def _extract_pallet_count(value: str) -> int | None:
    patterns = (
        r"^(\d+)_?(?:pallet|pallets|托|托数)(?:_?(?:price|usd|价格))?$",
        r"^(?:pallet|pallets|托|托数)_?(\d+)(?:_?(?:price|usd|价格))?$",
        r"^(?:base_price|price)_?(\d+)(?:_?usd)?$",
    )
    for pattern in patterns:
        match = re.fullmatch(pattern, value)
        if match:
            count = int(match.group(1))
            return count if count >= 1 else None
    return None


def _parse_origin(value: object, row: int, errors: list[SpreadsheetIssue]) -> str | None:
    raw = _optional_text(value)
    normalized = normalize_origin(raw)
    if normalized:
        return normalized
    errors.append(SpreadsheetIssue(row=row, field="origin", message="始发仓不能为空。"))
    return None


def _parse_positive_int(
    value: object,
    row: int,
    field_name: str,
    errors: list[SpreadsheetIssue],
) -> int | None:
    label = _field_label(field_name)
    if _is_blank(value):
        errors.append(SpreadsheetIssue(row=row, field=field_name, message=f"{label}不能为空。"))
        return None
    try:
        parsed = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        errors.append(SpreadsheetIssue(row=row, field=field_name, message=f"{label}必须是正整数。"))
        return None
    if not parsed.is_finite() or parsed < 1 or parsed != parsed.to_integral_value():
        errors.append(SpreadsheetIssue(row=row, field=field_name, message=f"{label}必须是正整数。"))
        return None
    return int(parsed)


def _parse_required_decimal(
    value: object,
    row: int,
    field_name: str,
    errors: list[SpreadsheetIssue],
) -> Decimal | None:
    label = _field_label(field_name)
    if _is_blank(value):
        errors.append(SpreadsheetIssue(row=row, field=field_name, message=f"{label}不能为空。"))
        return None
    try:
        parsed = Decimal(str(value).strip().replace(",", "").replace("$", ""))
    except (InvalidOperation, ValueError):
        errors.append(SpreadsheetIssue(row=row, field=field_name, message=f"{label}必须是非负数字。"))
        return None
    if not parsed.is_finite() or parsed < 0:
        errors.append(SpreadsheetIssue(row=row, field=field_name, message=f"{label}必须是非负数字。"))
        return None
    return parsed


def _parse_optional_decimal(
    value: object,
    row: int,
    field_name: str,
    errors: list[SpreadsheetIssue],
) -> Decimal | None:
    if _is_blank(value):
        return None
    return _parse_required_decimal(value, row, field_name, errors)


def _parse_last_updated(
    value: object,
    row: int,
    errors: list[SpreadsheetIssue],
) -> str:
    if _is_blank(value):
        return date.today().isoformat()
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    text = str(value).strip()
    if len(text) > 64:
        errors.append(SpreadsheetIssue(row=row, field="last_updated", message="更新日期不能超过 64 个字符。"))
        return date.today().isoformat()
    return text


def _optional_text(value: object) -> str | None:
    if _is_blank(value):
        return None
    text = str(value).strip()
    return text or None


def _is_blank(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _field_label(field_name: str) -> str:
    if field_name.endswith("_pallets") and field_name.split("_", 1)[0].isdigit():
        return f"{field_name.split('_', 1)[0]} 托价格"
    return {
        "origin": "始发仓",
        "zone": "Zone",
        "billing_pallets": "托数",
        "base_price_usd": "基础派送费",
        "fuel_percent": "燃油比例",
        "source": "来源备注",
        "last_updated": "更新日期",
    }.get(field_name, field_name)
