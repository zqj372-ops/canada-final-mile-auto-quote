from pathlib import Path

import pandas as pd

from packages.data_importer.validators import normalize_column_name, validate_rate_columns


def load_rate_card(path: Path) -> list[dict[str, object]]:
    if path.suffix.lower() == ".csv":
        frame = pd.read_csv(path)
    elif path.suffix.lower() in {".xlsx", ".xls"}:
        frame = pd.read_excel(path)
    else:
        raise ValueError(f"Unsupported rate card file type: {path.suffix}")

    frame = frame.rename(columns={column: normalize_column_name(str(column)) for column in frame.columns})
    validation = validate_rate_columns(list(frame.columns))
    if not validation.valid:
        missing = ", ".join(validation.missing_columns)
        raise ValueError(f"Rate card is missing required columns: {missing}")

    return frame.to_dict(orient="records")

