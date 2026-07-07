import httpx
from fastapi.testclient import TestClient

from apps.api.main import app


class FakeMapsClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        self.request_url = ""

    async def __aenter__(self) -> "FakeMapsClient":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        self.request_url = url
        return httpx.Response(
            200,
            content=b"<html>map</html>",
            headers={"content-type": "text/html; charset=utf-8", "x-frame-options": "SAMEORIGIN"},
            request=httpx.Request("GET", url),
        )


def test_maps_embed_proxies_google_without_frame_headers(monkeypatch) -> None:
    monkeypatch.setattr("apps.api.routes.maps.httpx.AsyncClient", FakeMapsClient)
    client = TestClient(app)

    response = client.get("/maps/embed", params={"query": "440 Hodgson Blvd NW Edmonton AB"})

    assert response.status_code == 200
    assert response.text == "<html>map</html>"
    assert response.headers["content-type"].startswith("text/html")
    assert "x-frame-options" not in response.headers


def test_maps_embed_rejects_empty_query() -> None:
    client = TestClient(app)

    response = client.get("/maps/embed", params={"query": "   "})

    assert response.status_code == 400
