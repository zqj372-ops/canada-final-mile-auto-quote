from pathlib import Path

from packages.data_importer.zone_loader import (
    load_postal_code_city_lookup,
    load_zone_lookup_rules,
    load_zone_price_matrix,
)


REFERENCE_DIR = Path("reference/canada-final-mile")


def test_zone_price_loader_flattens_matrix() -> None:
    rows = load_zone_price_matrix(REFERENCE_DIR / "Zone 票价表（查表价格）.json")

    assert {"origin", "zone", "billing_pallets", "base_price_usd"} <= set(rows[0])
    assert any(row["origin"] == "toronto" and row["zone"] == 2 for row in rows)


def test_zone_lookup_loader_reads_records() -> None:
    rows = load_zone_lookup_rules(REFERENCE_DIR / "Zone 邮编前缀 城市 省份 始发仓 查询表.json")

    assert len(rows) >= 1000
    assert any(row["postal_prefix"] == "L4K" and row["city"] == "CONCORD" for row in rows)


def test_postal_code_loader_normalizes_sample_records() -> None:
    rows = load_postal_code_city_lookup(REFERENCE_DIR / "canadapostalcodeslist(1).json")

    assert len(rows) >= 850000
    assert rows[0]["postal_code"].count(" ") == 1
    assert rows[0]["province"] is not None
