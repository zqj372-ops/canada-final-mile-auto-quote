from packages.data_importer.validators import REQUIRED_RATE_COLUMNS, validate_rate_columns


def test_validate_rate_columns_accepts_template() -> None:
    result = validate_rate_columns(REQUIRED_RATE_COLUMNS)

    assert result.valid is True
    assert result.missing_columns == []


def test_validate_rate_columns_reports_missing_columns() -> None:
    result = validate_rate_columns(["origin warehouse", "vendor name"])

    assert result.valid is False
    assert "base_cost_cad" in result.missing_columns

