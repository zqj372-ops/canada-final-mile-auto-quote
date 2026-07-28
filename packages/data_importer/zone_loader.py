from argparse import ArgumentParser
from collections import Counter
from pathlib import Path
import json
from typing import Any

from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.zone_lookup import (
    ORIGIN_BY_PROVINCE,
    get_province_from_postal_code,
    get_province_from_strict_fsa,
    normalize_origin,
)


def load_zone_price_matrix(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    source = payload.get("source")
    last_updated = payload.get("last_updated")
    rows: list[dict[str, object]] = []
    for origin_key in ("toronto", "calgary"):
        origin_prices = payload.get(origin_key, {})
        for zone, pallet_prices in origin_prices.items():
            for billing_pallets, base_price in pallet_prices.items():
                if base_price is None:
                    continue
                rows.append(
                    {
                        "origin": origin_key,
                        "zone": int(zone),
                        "billing_pallets": int(billing_pallets),
                        "base_price_usd": base_price,
                        "source": source,
                        "last_updated": last_updated,
                    }
                )
    return rows


def load_zone_lookup_rules(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records")
    if records is None:
        raise ValueError(
            "Zone reference quality gate failed: official format requires records and all data indexes."
        )
    if not isinstance(records, list):
        raise ValueError("Zone lookup records must be a JSON array.")

    validate_zone_records(records)
    validate_zone_reference_payload(payload)

    rows: list[dict[str, object]] = []
    for record in records:
        postal_prefix = str(record["postal_prefix"]).upper()
        province = normalize_province(str(record["province"]))
        if province is None:
            raise ValueError(f"Unknown province in validated Zone row: {record['province']}")
        rows.append(
            {
                "postal_prefix": postal_prefix,
                "city": (normalize_city(str(record["city"])) or str(record["city"])).upper(),
                "province": province,
                "origin": normalize_origin(str(record["origin"])) or str(record["origin"]),
                "zone": int(record["zone"]),
                "canonical_city": (
                    normalize_city(str(record.get("canonical_city") or record["city"])) or str(record.get("canonical_city") or record["city"])
                ).upper(),
                "priority": int(record.get("priority") or 100),
                "active": _parse_bool(record.get("active", True)),
                "match_level": record.get("match_level"),
                "note": record.get("note"),
            }
        )
    return rows


def validate_zone_records(records: list[dict[str, Any]]) -> None:
    """Reject malformed or cross-province Zone rows before any import occurs."""

    malformed_rows: list[str] = []
    cross_province_rows: list[str] = []
    origin_matrix_rows: list[str] = []
    business_keys: Counter[tuple[str, str, str, str, int]] = Counter()
    required_fields = ("postal_prefix", "city", "province", "origin", "zone")
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            malformed_rows.append(f"records[{index}] is not an object")
            continue
        missing = [field for field in required_fields if record.get(field) in (None, "")]
        if missing:
            malformed_rows.append(f"records[{index}] missing {','.join(missing)}")
            continue
        raw_postal_prefix = str(record["postal_prefix"])
        raw_city = str(record["city"])
        raw_province = str(record["province"])
        postal_prefix = raw_postal_prefix.upper()
        province = normalize_province(str(record["province"]))
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
            cross_province_rows.append(
                f"records[{index}] {postal_prefix} + {record['city']} + {province}"
            )
            continue
        expected_origin = ORIGIN_BY_PROVINCE.get(province)
        actual_origin = normalize_origin(str(record["origin"]))
        if expected_origin and actual_origin != expected_origin:
            origin_matrix_rows.append(
                f"records[{index}] {postal_prefix} + {province} expects "
                f"{expected_origin}, got {record['origin']}"
            )
            continue
        city = (normalize_city(str(record["city"])) or str(record["city"])).upper()
        business_keys[(postal_prefix, city, province, actual_origin or "", zone)] += 1

    duplicate_keys = [key for key, count in business_keys.items() if count > 1]

    if malformed_rows or cross_province_rows or origin_matrix_rows or duplicate_keys:
        examples = "; ".join(
            [
                *malformed_rows[:3],
                *cross_province_rows[:3],
                *origin_matrix_rows[:3],
                *(f"duplicate {key}" for key in duplicate_keys[:3]),
            ]
        )
        raise ValueError(
            "Zone reference quality gate failed: "
            f"malformed_error_count={len(malformed_rows)}; "
            f"cross_province_error_count={len(cross_province_rows)}; "
            f"origin_matrix_error_count={len(origin_matrix_rows)}; "
            f"duplicate_business_key_count={len(duplicate_keys)}; "
            f"examples={examples}"
        )


def build_zone_indexes(records: list[dict[str, Any]]) -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Build all derived indexes from records, using CITY|PROVINCE city keys."""

    indexes: dict[str, dict[str, list[dict[str, Any]]]] = {
        "by_postal_prefix": {},
        "by_city": {},
        "by_zone": {},
        "by_province": {},
    }
    for record in records:
        normalized = dict(record)
        postal_prefix = str(record["postal_prefix"]).strip().upper()
        city = (normalize_city(str(record["city"])) or str(record["city"])).upper()
        province = (normalize_province(str(record["province"])) or str(record["province"])).upper()
        zone = str(int(record["zone"]))
        keys = {
            "by_postal_prefix": postal_prefix,
            "by_city": f"{city}|{province}",
            "by_zone": zone,
            "by_province": province,
        }
        for index_name, key in keys.items():
            indexes[index_name].setdefault(key, []).append(normalized)

    for index in indexes.values():
        for key, rows in index.items():
            index[key] = sorted(rows, key=_zone_record_sort_key)
    return {name: dict(sorted(index.items())) for name, index in indexes.items()}


def validate_zone_reference_payload(payload: dict[str, Any]) -> None:
    """Enforce a zero-error, internally consistent raw Zone JSON artifact."""

    records = payload.get("records")
    if not isinstance(records, list):
        raise ValueError("Zone reference quality gate failed: records must be an array.")
    validate_zone_records(records)

    errors: list[str] = []
    if payload.get("total_records") != len(records):
        errors.append(
            f"total_records={payload.get('total_records')} but records={len(records)}"
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        errors.append("data indexes are missing")
    else:
        expected = build_zone_indexes(records)
        for index_name, expected_index in expected.items():
            actual_index = data.get(index_name)
            if not isinstance(actual_index, dict):
                errors.append(f"{index_name} is missing")
                continue
            if index_name == "by_city":
                plain_keys = [key for key in actual_index if "|" not in str(key)]
                if plain_keys:
                    errors.append(
                        "by_city must use CITY|PROVINCE keys; "
                        f"plain_key_count={len(plain_keys)} examples={plain_keys[:5]}"
                    )
            if set(actual_index) != set(expected_index):
                errors.append(f"{index_name} key set does not match canonical records")
            if _index_counter(actual_index) != _index_counter(expected_index):
                errors.append(f"{index_name} does not match canonical records")

    if errors:
        raise ValueError(
            "Zone reference quality gate failed: " + "; ".join(errors)
        )


def load_postal_code_city_lookup(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Postal code lookup must be a JSON object keyed by postal code.")

    rows: list[dict[str, object]] = []
    for raw_postal_code, preferred_city in payload.items():
        postal_code = normalize_postal_code(raw_postal_code)
        if postal_code is None:
            continue
        rows.append(
            {
                "postal_code": postal_code,
                "preferred_city": normalize_city(str(preferred_city)) or str(preferred_city),
                "province": get_province_from_postal_code(postal_code),
                "fsa": extract_fsa(postal_code),
                "official_city": normalize_city(str(preferred_city)) or str(preferred_city),
                "municipality": None,
                "source": "postal_code_lookup_import",
            }
        )
    return rows


def load_city_aliases(path: Path) -> list[dict[str, object]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        records = payload.get("records")
        if records is None:
            records = _flatten_alias_mapping(payload)
    elif isinstance(payload, list):
        records = payload
    else:
        raise ValueError("City aliases must be a JSON object or list.")

    rows: list[dict[str, object]] = []
    for record in records:
        province = normalize_province(str(record["province"]))
        alias_city = normalize_city(str(record["alias_city"]))
        canonical_city = normalize_city(str(record["canonical_city"]))
        if province is None or alias_city is None or canonical_city is None:
            continue
        rows.append(
            {
                "province": province,
                "alias_city": alias_city.upper(),
                "canonical_city": canonical_city.upper(),
                "alias_type": record.get("alias_type"),
                "active": _parse_bool(record.get("active", True)),
                "source": record.get("source"),
                "note": record.get("note"),
            }
        )
    return rows


def _flatten_prefix_index(index: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for records in index.values():
        rows.extend(records)
    return rows


def _flatten_alias_mapping(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for province, aliases in payload.items():
        if province == "records":
            continue
        if not isinstance(aliases, dict):
            continue
        for alias_city, canonical_city in aliases.items():
            rows.append(
                {
                    "province": province,
                    "alias_city": alias_city,
                    "canonical_city": canonical_city,
                    "alias_type": "mapping",
                }
            )
    return rows


def _zone_record_sort_key(record: dict[str, Any]) -> tuple[str, str, str, str, int, str]:
    return (
        str(record.get("postal_prefix") or "").upper(),
        str(record.get("city") or "").upper(),
        str(record.get("province") or "").upper(),
        str(record.get("origin") or ""),
        int(record.get("zone") or 0),
        json.dumps(record, ensure_ascii=False, sort_keys=True),
    )


def _index_counter(index: dict[str, list[dict[str, Any]]]) -> Counter[tuple[str, str]]:
    rows: Counter[tuple[str, str]] = Counter()
    for key, records in index.items():
        if not isinstance(records, list):
            rows[(str(key), "<not-a-list>")] += 1
            continue
        for record in records:
            rows[(str(key), json.dumps(record, ensure_ascii=False, sort_keys=True))] += 1
    return rows


def _parse_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() not in {"0", "false", "no", "off", "inactive"}


def main() -> None:
    parser = ArgumentParser(description="Load Canada final-mile zone JSON files and print normalized row counts.")
    parser.add_argument("--zone-prices", type=Path)
    parser.add_argument("--zone-lookup", type=Path)
    parser.add_argument("--postal-codes", type=Path)
    parser.add_argument("--city-aliases", type=Path)
    args = parser.parse_args()

    if args.zone_prices:
        print(f"zone_price_matrix={len(load_zone_price_matrix(args.zone_prices))}")
    if args.zone_lookup:
        print(f"zone_lookup_rules={len(load_zone_lookup_rules(args.zone_lookup))}")
    if args.postal_codes:
        print(f"postal_code_city_lookup={len(load_postal_code_city_lookup(args.postal_codes))}")
    if args.city_aliases:
        print(f"city_aliases={len(load_city_aliases(args.city_aliases))}")


if __name__ == "__main__":
    main()
