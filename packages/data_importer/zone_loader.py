from argparse import ArgumentParser
from pathlib import Path
import json
from typing import Any

from packages.address_normalizer import extract_fsa, normalize_city, normalize_postal_code, normalize_province
from packages.quote_engine.zone_lookup import get_province_from_postal_code, normalize_origin


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
        records = _flatten_prefix_index(payload.get("data", {}).get("by_postal_prefix", {}))

    rows: list[dict[str, object]] = []
    for record in records:
        rows.append(
            {
                "postal_prefix": str(record["postal_prefix"]).upper(),
                "city": (normalize_city(str(record["city"])) or str(record["city"])).upper(),
                "province": str(record["province"]).upper(),
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
