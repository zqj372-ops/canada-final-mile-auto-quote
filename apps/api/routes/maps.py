from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse


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
