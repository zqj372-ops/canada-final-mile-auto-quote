import json
from pathlib import Path

import pytest

from packages.data_importer.zone_loader import (
    build_zone_indexes,
    load_city_aliases,
    load_postal_code_city_lookup,
    load_zone_lookup_rules,
    load_zone_price_matrix,
    validate_zone_records,
    validate_zone_reference_payload,
)
from scripts.maintain_zone_reference import repair_payload


REFERENCE_DIR = Path("reference/canada-final-mile")


def test_zone_price_loader_flattens_matrix() -> None:
    rows = load_zone_price_matrix(REFERENCE_DIR / "Zone 票价表（查表价格）.json")

    assert {"origin", "zone", "billing_pallets", "base_price_usd"} <= set(rows[0])
    assert any(row["origin"] == "toronto" and row["zone"] == 2 for row in rows)


def test_zone_lookup_loader_reads_records() -> None:
    rows = load_zone_lookup_rules(REFERENCE_DIR / "Zone 邮编前缀 城市 省份 始发仓 查询表.json")

    assert len(rows) >= 1000
    assert any(row["postal_prefix"] == "L4K" and row["city"] == "CONCORD" for row in rows)
    assert any(
        row["postal_prefix"] == "S4S"
        and row["city"] == "REGINA"
        and row["province"] == "SK"
        and row["origin"] == "calgary"
        and row["zone"] == 5
        for row in rows
    )
    assert any(
        row["postal_prefix"] == "T6R"
        and row["city"] == "EDMONTON"
        and row["province"] == "AB"
        and row["origin"] == "calgary"
        and row["zone"] == 9
        for row in rows
    )
    assert any(
        row["postal_prefix"] == "V4C"
        and row["city"] == "DELTA"
        and row["province"] == "BC"
        and row["origin"] == "calgary"
        and row["zone"] == 5
        for row in rows
    )
    assert not any(
        row["postal_prefix"] == "K0E"
        and row["city"] == "DELTA"
        and row["province"] == "BC"
        for row in rows
    )
    assert {"canonical_city", "priority", "active"} <= set(rows[0])


def test_zone_lookup_loader_rejects_cross_province_rows_instead_of_silently_filtering(
    tmp_path: Path,
) -> None:
    path = tmp_path / "dirty-zone-rules.json"
    path.write_text(
        json.dumps(
            {
                "records": [
                    {
                        "postal_prefix": "K0E",
                        "city": "DELTA",
                        "province": "BC",
                        "origin": "多伦多",
                        "zone": 10,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="cross_province_error_count=1"):
        load_zone_lookup_rules(path)


@pytest.mark.parametrize(
    ("postal_prefix", "province", "origin", "expected_error"),
    [
        ("ZZZ", "BC", "卡尔加里", "malformed_error_count=1"),
        ("V4", "BC", "卡尔加里", "malformed_error_count=1"),
        (" V4C ", "BC", "卡尔加里", "malformed_error_count=1"),
        ("v4c", "BC", "卡尔加里", "malformed_error_count=1"),
        ("X0A", "NT", "卡尔加里", "cross_province_error_count=1"),
        ("X0E", "NU", "卡尔加里", "cross_province_error_count=1"),
        ("V4C", "BC", "多伦多", "origin_matrix_error_count=1"),
    ],
)
def test_zone_quality_gate_rejects_invalid_fsa_province_and_origin_matrix(
    postal_prefix: str,
    province: str,
    origin: str,
    expected_error: str,
) -> None:
    records = [
        {
            "postal_prefix": postal_prefix,
            "city": "TEST",
            "province": province,
            "origin": origin,
            "zone": 5,
        }
    ]

    with pytest.raises(ValueError, match=expected_error):
        validate_zone_records(records)


def test_zone_lookup_loader_requires_complete_derived_indexes(tmp_path: Path) -> None:
    path = tmp_path / "records-only.json"
    path.write_text(
        json.dumps(
            {
                "total_records": 1,
                "records": [
                    {
                        "postal_prefix": "V4C",
                        "city": "DELTA",
                        "province": "BC",
                        "origin": "卡尔加里",
                        "zone": 5,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="data indexes are missing"):
        load_zone_lookup_rules(path)


def test_zone_reference_quality_gate_requires_composite_city_province_indexes() -> None:
    payload = json.loads(
        (REFERENCE_DIR / "Zone 邮编前缀 城市 省份 始发仓 查询表.json").read_text(encoding="utf-8")
    )

    validate_zone_reference_payload(payload)

    assert all("|" in key for key in payload["data"]["by_city"])
    assert payload["total_records"] == len(payload["records"])


def test_zone_reference_quality_gate_rejects_extra_empty_index_keys() -> None:
    records = [
        {
            "postal_prefix": "V4C",
            "city": "DELTA",
            "province": "BC",
            "origin": "卡尔加里",
            "zone": 5,
        }
    ]
    payload = {
        "total_records": 1,
        "records": records,
        "data": build_zone_indexes(records),
    }
    payload["data"]["by_city"]["GHOST|BC"] = []

    with pytest.raises(ValueError, match="by_city key set"):
        validate_zone_reference_payload(payload)


def test_zone_reference_repair_is_idempotent_and_removes_duplicate_keys() -> None:
    duplicate = {
        "postal_prefix": "H8R",
        "city": "LACHINE",
        "province": "QC",
        "origin": "多伦多",
        "zone": 7,
        "note": "",
    }
    payload = {
        "total_records": 2,
        "records": [duplicate, {**duplicate, "note": "preferred evidence"}],
        "data": build_zone_indexes([duplicate, {**duplicate, "note": "preferred evidence"}]),
    }

    repaired, report = repair_payload(payload, last_updated="2026-07-28")
    repaired_twice, second_report = repair_payload(
        repaired,
        last_updated="2026-07-28",
    )

    assert report["removed_duplicate_records"] == 1
    assert second_report["removed_duplicate_records"] == 0
    assert repaired_twice == repaired
    validate_zone_reference_payload(repaired)


def test_zone_reference_repair_refuses_to_silently_delete_malformed_rows() -> None:
    payload = {"records": [123], "data": {}, "total_records": 1}

    with pytest.raises(ValueError, match="Refusing to repair malformed Zone records"):
        repair_payload(payload, last_updated="2026-07-28")


def test_white_rock_v4b_correction_is_consistent_across_zone_indexes() -> None:
    payload = json.loads(
        (REFERENCE_DIR / "Zone 邮编前缀 城市 省份 始发仓 查询表.json").read_text(encoding="utf-8")
    )

    def is_corrected_white_rock_rule(row: dict[str, object]) -> bool:
        return (
            row.get("postal_prefix") == "V4B"
            and row.get("city") == "WHITE ROCK"
            and row.get("province", "BC") == "BC"
            and row.get("origin") == "卡尔加里"
            and row.get("zone") == 5
        )

    data = payload["data"]
    assert any(is_corrected_white_rock_rule(row) for row in data["by_postal_prefix"]["V4B"])
    assert any(is_corrected_white_rock_rule(row) for row in data["by_city"]["WHITE ROCK|BC"])
    assert any(is_corrected_white_rock_rule(row) for row in data["by_zone"]["5"])
    assert any(is_corrected_white_rock_rule(row) for row in data["by_province"]["BC"])
    assert any(is_corrected_white_rock_rule(row) for row in payload["records"])
    assert not any(
        row.get("postal_prefix") == "B4P"
        and row.get("city") == "WHITE ROCK"
        and row.get("province") == "BC"
        for row in payload["records"]
    )


def test_postal_code_loader_normalizes_sample_records() -> None:
    rows = load_postal_code_city_lookup(REFERENCE_DIR / "canadapostalcodeslist(1).json")

    assert len(rows) >= 850000
    assert rows[0]["postal_code"].count(" ") == 1
    assert rows[0]["province"] is not None
    assert rows[0]["fsa"] is not None
    assert any(
        row["postal_code"] == "V3X 0L7"
        and row["preferred_city"] == "Surrey"
        and row["province"] == "BC"
        and row["fsa"] == "V3X"
        for row in rows
    )
    assert any(
        row["postal_code"] == "V3J 0A7"
        and row["preferred_city"] == "Burnaby"
        and row["province"] == "BC"
        and row["fsa"] == "V3J"
        for row in rows
    )
    assert any(
        row["postal_code"] == "V4B 2C5"
        and row["preferred_city"] == "White Rock"
        and row["province"] == "BC"
        and row["fsa"] == "V4B"
        for row in rows
    )


def test_city_alias_loader_reads_records(tmp_path: Path) -> None:
    path = tmp_path / "aliases.json"
    path.write_text(
        """
        {
          "records": [
            {"province": "ON", "alias_city": "Concord", "canonical_city": "Vaughan", "alias_type": "suburb"}
          ]
        }
        """,
        encoding="utf-8",
    )

    rows = load_city_aliases(path)

    assert rows == [
        {
            "province": "ON",
            "alias_city": "CONCORD",
            "canonical_city": "VAUGHAN",
            "alias_type": "suburb",
            "active": True,
            "source": None,
            "note": None,
        }
    ]
