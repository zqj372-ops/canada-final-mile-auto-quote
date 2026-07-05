from argparse import ArgumentParser
from pathlib import Path
import json
from typing import Any

from packages.address_normalizer import normalize_city, normalize_postal_code
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
            }
        )
    return rows


def _flatten_prefix_index(index: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for records in index.values():
        rows.extend(records)
    return rows


def main() -> None:
    parser = ArgumentParser(description="Load Canada final-mile zone JSON files and print normalized row counts.")
    parser.add_argument("--zone-prices", type=Path)
    parser.add_argument("--zone-lookup", type=Path)
    parser.add_argument("--postal-codes", type=Path)
    args = parser.parse_args()

    if args.zone_prices:
        print(f"zone_price_matrix={len(load_zone_price_matrix(args.zone_prices))}")
    if args.zone_lookup:
        print(f"zone_lookup_rules={len(load_zone_lookup_rules(args.zone_lookup))}")
    if args.postal_codes:
        print(f"postal_code_city_lookup={len(load_postal_code_city_lookup(args.postal_codes))}")


if __name__ == "__main__":
    main()
