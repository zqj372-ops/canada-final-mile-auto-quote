from decimal import Decimal

import pandas as pd

from packages.data_importer.zone_price_spreadsheet import load_zone_price_spreadsheet


def test_loads_long_form_csv_and_normalizes_origin(tmp_path) -> None:
    path = tmp_path / "prices.csv"
    path.write_text(
        "origin,billing_pallets,zone,base_price_usd,fuel_percent,source,last_updated\n"
        "多伦多,3,2,150.25,36.5,supplier,2026-07-17\n",
        encoding="utf-8",
    )

    result = load_zone_price_spreadsheet(path)

    assert result.can_import is True
    assert result.source_row_count == 1
    assert result.rows == [
        {
            "row_number": 2,
            "origin": "toronto",
            "zone": 2,
            "billing_pallets": 3,
            "base_price_usd": Decimal("150.25"),
            "fuel_percent": Decimal("36.5"),
            "source": "supplier",
            "last_updated": "2026-07-17",
        }
    ]
    assert result.fuel_overrides == {"toronto|2": Decimal("36.5")}


def test_loads_wide_form_xlsx(tmp_path) -> None:
    path = tmp_path / "prices.xlsx"
    pd.DataFrame(
        [
            {
                "始发仓": "calgary",
                "Zone": 4,
                "燃油附加比例(%)": 40,
                "1托": 100,
                "2托": 175.5,
            }
        ]
    ).to_excel(path, index=False)

    result = load_zone_price_spreadsheet(path)

    assert result.can_import is True
    assert [row["billing_pallets"] for row in result.rows] == [1, 2]
    assert [row["base_price_usd"] for row in result.rows] == [Decimal("100"), Decimal("175.5")]


def test_duplicate_long_form_price_key_is_reported(tmp_path) -> None:
    path = tmp_path / "prices.csv"
    path.write_text(
        "origin,zone,billing_pallets,base_price_usd\n"
        "toronto,2,1,120\n"
        "toronto,2,1,125\n",
        encoding="utf-8",
    )

    result = load_zone_price_spreadsheet(path)

    assert result.can_import is False
    assert len(result.rows) == 1
    assert result.errors[0].row == 3
    assert "重复" in result.errors[0].message
