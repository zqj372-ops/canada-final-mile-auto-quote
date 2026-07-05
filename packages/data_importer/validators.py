from pydantic import BaseModel, Field


REQUIRED_RATE_COLUMNS = [
    "origin_warehouse",
    "vendor_name",
    "province",
    "city",
    "fsa",
    "postal_code",
    "pallet_min",
    "pallet_max",
    "weight_min_kg",
    "weight_max_kg",
    "base_cost_cad",
    "fuel_percent",
    "appointment_fee_cad",
    "liftgate_fee_cad",
    "residential_fee_cad",
    "limited_access_fee_cad",
    "remote_fee_cad",
    "effective_from",
    "effective_to",
    "status",
]


class ImportValidationResult(BaseModel):
    valid: bool
    missing_columns: list[str] = Field(default_factory=list)
    extra_columns: list[str] = Field(default_factory=list)


def normalize_column_name(value: str) -> str:
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def validate_rate_columns(columns: list[str]) -> ImportValidationResult:
    normalized = [normalize_column_name(column) for column in columns]
    missing = [column for column in REQUIRED_RATE_COLUMNS if column not in normalized]
    extra = [column for column in normalized if column not in REQUIRED_RATE_COLUMNS]
    return ImportValidationResult(valid=not missing, missing_columns=missing, extra_columns=extra)

