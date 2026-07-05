from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import APIRouter, File, HTTPException, UploadFile

from packages.data_importer.excel_loader import load_rate_card


router = APIRouter(prefix="/imports", tags=["imports"])


@router.post("/validate")
async def validate_import(file: UploadFile = File(...)) -> dict[str, object]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="Only CSV and Excel files are supported.")

    with NamedTemporaryFile(suffix=suffix, delete=True) as temp_file:
        temp_file.write(await file.read())
        temp_file.flush()
        rows = load_rate_card(Path(temp_file.name))

    return {"status": "valid", "row_count": len(rows)}

