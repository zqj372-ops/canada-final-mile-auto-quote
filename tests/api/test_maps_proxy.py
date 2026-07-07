from fastapi.testclient import TestClient

from apps.api.main import app


def test_maps_embed_redirects_to_google_embed_url() -> None:
    client = TestClient(app)

    response = client.get(
        "/maps/embed",
        params={"query": "440  Hodgson Blvd NW   Edmonton AB"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == (
        "https://maps.google.com/maps?output=embed&q=440+Hodgson+Blvd+NW+Edmonton+AB"
    )
    assert response.headers["cache-control"] == "public, max-age=3600"


def test_maps_embed_rejects_empty_query() -> None:
    client = TestClient(app)

    response = client.get("/maps/embed", params={"query": "   "})

    assert response.status_code == 400
