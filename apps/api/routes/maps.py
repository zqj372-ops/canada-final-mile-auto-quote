from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from apps.api.db.session import get_db
from apps.api.services.address_validation_service import LocalAddressValidation, build_local_address_validation

router = APIRouter(prefix="/maps", tags=["maps"])


@router.get("/embed")
async def google_maps_embed(query: str = Query(min_length=1, max_length=500)) -> RedirectResponse:
    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Map query is required.")

    google_url = "https://maps.google.com/maps?" + urlencode(
        {"output": "embed", "q": normalized_query}
    )

    return RedirectResponse(
        google_url,
        status_code=302,
        headers={"Cache-Control": "public, max-age=3600"},
    )


@router.get("/local-verify", response_model=LocalAddressValidation)
async def local_address_verify(
    address_line: str | None = Query(default=None, max_length=500),
    postal_code: str | None = Query(default=None, max_length=32),
    city: str | None = Query(default=None, max_length=128),
    province: str | None = Query(default=None, max_length=64),
    db: Session = Depends(get_db),
) -> LocalAddressValidation:
    return build_local_address_validation(
        db,
        address_line=address_line,
        postal_code=postal_code,
        city=city,
        province=province,
    )
