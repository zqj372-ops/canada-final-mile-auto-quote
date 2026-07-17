from pathlib import Path
from tempfile import NamedTemporaryFile
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.models import CityAlias, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.repositories.quote_rule_config_repository import QuoteRuleConfigRepository
from apps.api.db.session import get_db
from packages.data_importer.excel_loader import load_rate_card
from packages.data_importer.zone_price_spreadsheet import ZonePriceSpreadsheet, load_zone_price_spreadsheet
from packages.data_importer.zone_loader import (
    load_city_aliases,
    load_postal_code_city_lookup,
    load_zone_lookup_rules,
    load_zone_price_matrix,
)


router = APIRouter(prefix="/imports", tags=["imports"], dependencies=[Depends(require_roles(*ADMIN_ROLES))])

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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


@router.post("/zone-rules")
async def import_zone_rules(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, object]:
    rows = await _load_json_rows(file, load_zone_lookup_rules)
    result = _upsert_rows(
        db,
        ZoneLookupRule,
        rows,
        key_fields=("postal_prefix", "city", "province", "origin", "zone"),
        update_fields=("canonical_city", "priority", "active", "match_level", "note"),
    )
    return {"status": "imported", "resource": "zone_lookup_rules", **result}


@router.post("/zone-price-matrix/preview")
async def preview_zone_price_matrix(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> dict[str, object]:
    spreadsheet = await _load_zone_price_table(file)
    return _build_zone_price_preview(db, spreadsheet, filename=file.filename or "")


@router.post("/zone-price-matrix")
async def import_zone_price_matrix(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, object]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix == ".json":
        rows = await _load_json_rows(file, load_zone_price_matrix)
        result = _upsert_rows(
            db,
            ZonePriceMatrix,
            rows,
            key_fields=("origin", "zone", "billing_pallets"),
            update_fields=("base_price_usd", "source", "last_updated"),
        )
        return {"status": "imported", "resource": "zone_price_matrix", **result}

    spreadsheet = await _load_zone_price_table(file)
    if not spreadsheet.can_import:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "表格校验未通过，请修正后重新上传。",
                "errors": [issue.to_dict() for issue in spreadsheet.errors[:50]],
            },
        )

    price_rows = [
        {
            "origin": row["origin"],
            "zone": row["zone"],
            "billing_pallets": row["billing_pallets"],
            "base_price_usd": row["base_price_usd"],
            "source": row["source"],
            "last_updated": row["last_updated"],
        }
        for row in spreadsheet.rows
    ]
    pricing_repository = QuoteRuleConfigRepository(db)
    pricing_config = pricing_repository.get_zone_pricing_config()
    fuel_change_count = sum(
        pricing_config.fuel_percent_by_zone.get(key) != value
        for key, value in spreadsheet.fuel_overrides.items()
    )

    try:
        result = _upsert_rows(
            db,
            ZonePriceMatrix,
            price_rows,
            key_fields=("origin", "zone", "billing_pallets"),
            update_fields=("base_price_usd", "source", "last_updated"),
            commit=False,
        )
        if spreadsheet.fuel_overrides:
            next_fuel_overrides = {
                **pricing_config.fuel_percent_by_zone,
                **spreadsheet.fuel_overrides,
            }
            pricing_repository.save_zone_pricing_config(
                pricing_config.model_copy(update={"fuel_percent_by_zone": next_fuel_overrides})
            )
        else:
            db.commit()
    except Exception:
        db.rollback()
        raise

    return {
        "status": "imported",
        "resource": "zone_price_matrix",
        "filename": file.filename or "",
        "source_row_count": spreadsheet.source_row_count,
        "fuel_override_count": len(spreadsheet.fuel_overrides),
        "fuel_updated_count": fuel_change_count,
        **result,
    }


@router.post("/postal-code-lookup")
async def import_postal_code_lookup(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, object]:
    rows = await _load_json_rows(file, load_postal_code_city_lookup)
    result = _upsert_rows(
        db,
        PostalCodeCityLookup,
        rows,
        key_fields=("postal_code",),
        update_fields=("preferred_city", "province", "fsa", "official_city", "municipality", "latitude", "longitude", "source"),
    )
    return {"status": "imported", "resource": "postal_code_city_lookup", **result}


@router.post("/city-aliases")
async def import_city_aliases(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, object]:
    rows = await _load_json_rows(file, load_city_aliases)
    result = _upsert_rows(
        db,
        CityAlias,
        rows,
        key_fields=("province", "alias_city"),
        update_fields=("canonical_city", "alias_type", "active", "source", "note"),
    )
    return {"status": "imported", "resource": "city_aliases", **result}


async def _load_json_rows(
    file: UploadFile,
    loader: Callable[[Path], list[dict[str, object]]],
) -> list[dict[str, object]]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix != ".json":
        raise HTTPException(status_code=400, detail="Only JSON files are supported for this import.")

    try:
        with NamedTemporaryFile(suffix=suffix, delete=True) as temp_file:
            temp_file.write(await file.read())
            temp_file.flush()
            return loader(Path(temp_file.name))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Invalid import file: {exc}") from exc


async def _load_zone_price_table(file: UploadFile) -> ZonePriceSpreadsheet:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in {".csv", ".xlsx", ".xls"}:
        raise HTTPException(status_code=400, detail="仅支持 CSV、XLSX 和 XLS 表格。")

    contents = await file.read()
    if not contents:
        raise HTTPException(status_code=400, detail="上传的表格为空。")
    if len(contents) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="表格不能超过 10 MB。")

    try:
        with NamedTemporaryFile(suffix=suffix, delete=True) as temp_file:
            temp_file.write(contents)
            temp_file.flush()
            return load_zone_price_spreadsheet(Path(temp_file.name))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _build_zone_price_preview(
    db: Session,
    spreadsheet: ZonePriceSpreadsheet,
    *,
    filename: str,
) -> dict[str, object]:
    existing_keys = {
        (str(origin), int(zone), int(billing_pallets))
        for origin, zone, billing_pallets in db.execute(
            select(ZonePriceMatrix.origin, ZonePriceMatrix.zone, ZonePriceMatrix.billing_pallets)
        ).all()
    }
    inserted_count = 0
    updated_count = 0
    preview_rows: list[dict[str, object]] = []
    for row in spreadsheet.rows:
        key = (str(row["origin"]), int(row["zone"]), int(row["billing_pallets"]))
        action = "update" if key in existing_keys else "insert"
        if action == "update":
            updated_count += 1
        else:
            inserted_count += 1
        if len(preview_rows) < 8:
            preview_rows.append(
                {
                    "row": row["row_number"],
                    "origin": row["origin"],
                    "zone": row["zone"],
                    "billing_pallets": row["billing_pallets"],
                    "base_price_usd": str(row["base_price_usd"]),
                    "fuel_percent": (
                        str(row["fuel_percent"])
                        if row.get("fuel_percent") is not None
                        else None
                    ),
                    "action": action,
                }
            )

    pricing_config = QuoteRuleConfigRepository(db).get_zone_pricing_config()
    fuel_updated_count = sum(
        pricing_config.fuel_percent_by_zone.get(key) != value
        for key, value in spreadsheet.fuel_overrides.items()
    )
    invalid_rows = {issue.row for issue in spreadsheet.errors if issue.row is not None}
    return {
        "status": "valid" if spreadsheet.can_import else "invalid",
        "can_import": spreadsheet.can_import,
        "filename": filename,
        "source_row_count": spreadsheet.source_row_count,
        "row_count": len(spreadsheet.rows),
        "invalid_row_count": len(invalid_rows),
        "inserted_count": inserted_count,
        "updated_count": updated_count,
        "fuel_override_count": len(spreadsheet.fuel_overrides),
        "fuel_updated_count": fuel_updated_count,
        "preview_rows": preview_rows,
        "errors": [issue.to_dict() for issue in spreadsheet.errors[:50]],
        "warnings": [issue.to_dict() for issue in spreadsheet.warnings[:20]],
    }


def _upsert_rows(
    db: Session,
    model: type,
    rows: list[dict[str, object]],
    *,
    key_fields: tuple[str, ...],
    update_fields: tuple[str, ...],
    commit: bool = True,
) -> dict[str, int]:
    inserted = 0
    updated = 0
    skipped = 0
    try:
        for row in rows:
            if any(row.get(field) is None for field in key_fields):
                skipped += 1
                continue
            query = select(model)
            for field in key_fields:
                query = query.where(getattr(model, field) == row[field])
            record = db.scalars(query).first()
            if record is None:
                db.add(model(**row))
                inserted += 1
                continue
            for field in update_fields:
                if field in row:
                    setattr(record, field, row[field])
            updated += 1
        if commit:
            db.commit()
        else:
            db.flush()
    except Exception:
        db.rollback()
        raise
    return {
        "row_count": len(rows),
        "inserted_count": inserted,
        "updated_count": updated,
        "skipped_count": skipped,
    }
