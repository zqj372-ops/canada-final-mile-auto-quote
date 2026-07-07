from pathlib import Path
from tempfile import NamedTemporaryFile
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from apps.api.auth import ADMIN_ROLES, require_roles
from apps.api.db.models import CityAlias, PostalCodeCityLookup, ZoneLookupRule, ZonePriceMatrix
from apps.api.db.session import get_db
from packages.data_importer.excel_loader import load_rate_card
from packages.data_importer.zone_loader import (
    load_city_aliases,
    load_postal_code_city_lookup,
    load_zone_lookup_rules,
    load_zone_price_matrix,
)


router = APIRouter(prefix="/imports", tags=["imports"], dependencies=[Depends(require_roles(*ADMIN_ROLES))])


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


@router.post("/zone-price-matrix")
async def import_zone_price_matrix(file: UploadFile = File(...), db: Session = Depends(get_db)) -> dict[str, object]:
    rows = await _load_json_rows(file, load_zone_price_matrix)
    result = _upsert_rows(
        db,
        ZonePriceMatrix,
        rows,
        key_fields=("origin", "zone", "billing_pallets"),
        update_fields=("base_price_usd", "source", "last_updated"),
    )
    return {"status": "imported", "resource": "zone_price_matrix", **result}


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


def _upsert_rows(
    db: Session,
    model: type,
    rows: list[dict[str, object]],
    *,
    key_fields: tuple[str, ...],
    update_fields: tuple[str, ...],
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
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {
        "row_count": len(rows),
        "inserted_count": inserted,
        "updated_count": updated,
        "skipped_count": skipped,
    }
