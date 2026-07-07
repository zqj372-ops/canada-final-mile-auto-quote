from __future__ import annotations

import os
import sys
from argparse import ArgumentParser
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, delete

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from apps.api.db.models import PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from packages.data_importer.zone_loader import (
    load_postal_code_city_lookup,
    load_zone_lookup_rules,
    load_zone_price_matrix,
)


DEFAULT_REFERENCE_DIR = Path("reference/canada-final-mile")
CHUNK_SIZE = 5000


def main() -> None:
    parser = ArgumentParser(description="Load Canada final-mile reference JSON into PostgreSQL.")
    parser.add_argument("--reference-dir", type=Path, default=DEFAULT_REFERENCE_DIR)
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--skip-postal-codes", action="store_true")
    args = parser.parse_args()

    if not args.database_url:
        raise SystemExit("DATABASE_URL is required.")

    reference_dir = args.reference_dir
    zone_rows = load_zone_lookup_rules(reference_dir / "Zone 邮编前缀 城市 省份 始发仓 查询表.json")
    price_rows = load_zone_price_matrix(reference_dir / "Zone 票价表（查表价格）.json")
    postal_rows = [] if args.skip_postal_codes else load_postal_code_city_lookup(reference_dir / "canadapostalcodeslist(1).json")

    engine = create_engine(args.database_url)
    with engine.begin() as connection:
        connection.execute(delete(ZoneLookupRule))
        connection.execute(delete(ZonePriceMatrix))
        if not args.skip_postal_codes:
            connection.execute(delete(PostalCodeCityLookup))

        _insert_chunks(connection, ZoneLookupRule.__table__, zone_rows)
        _insert_chunks(connection, ZonePriceMatrix.__table__, price_rows)
        if not args.skip_postal_codes:
            _insert_chunks(connection, PostalCodeCityLookup.__table__, postal_rows)

    print(f"zone_lookup_rules={len(zone_rows)}")
    print(f"zone_price_matrix={len(price_rows)}")
    if not args.skip_postal_codes:
        print(f"postal_code_city_lookup={len(postal_rows)}")


def _insert_chunks(connection: Any, table: Any, rows: list[dict[str, object]]) -> None:
    for chunk in _chunks(rows, CHUNK_SIZE):
        connection.execute(table.insert(), chunk)


def _chunks(rows: list[dict[str, object]], size: int) -> Iterable[list[dict[str, object]]]:
    for index in range(0, len(rows), size):
        yield rows[index : index + size]


if __name__ == "__main__":
    main()
