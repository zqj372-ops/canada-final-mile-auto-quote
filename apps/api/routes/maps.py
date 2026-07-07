from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, HTTPException, Query, Response


router = APIRouter(prefix="/maps", tags=["maps"])


@router.get("/embed")
async def google_maps_embed(query: str = Query(min_length=1, max_length=500)) -> Response:
    normalized_query = " ".join(query.split())
    if not normalized_query:
        raise HTTPException(status_code=400, detail="Map query is required.")

    google_url = "https://www.google.com/maps?" + urlencode(
        {"q": normalized_query, "output": "embed"}
    )

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            upstream = await client.get(
                google_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/126.0 Safari/537.36"
                    ),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                },
            )
            upstream.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="Google Maps proxy request failed.") from exc

    return Response(
        content=upstream.content,
        media_type=upstream.headers.get("content-type", "text/html; charset=utf-8"),
        headers={"Cache-Control": "public, max-age=3600"},
    )
