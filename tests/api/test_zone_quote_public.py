from tests.api.test_zone_quotes import base_payload, build_client
from apps.api.main import app


def teardown_function() -> None:
    app.dependency_overrides.clear()


def _complete_handling_units() -> list[dict[str, object]]:
    return [
        {
            "quantity": 1,
            "packaging_type": "crate",
            "length_cm": 200,
            "width_cm": 130,
            "height_cm": 100,
            "unit_weight_kg": 900,
        }
    ]


def test_zone_http_success_returns_public_allowlist_only() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            cbm=2.6,
            weight_kg=900,
            piece_count=1,
            longest_side_cm=200,
            requires_appointment=False,
            handling_units=_complete_handling_units(),
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "quote_id",
        "billing_pallets",
        "total_price_usd",
        "sales_note",
        "manual_review_required",
        "public_flags",
    }
    assert body["billing_pallets"] == 3
    # v2 has no oversize surcharge: base 120 x 1.35 fuel.
    assert body["total_price_usd"] == "162.00"
    assert body["manual_review_required"] is False
    for hidden_field in (
        "pallet_breakdown",
        "accessorials",
        "internal_trace",
        "oversize_rule_snapshot",
        "match_trace",
        "risk_tags",
        "origin",
        "zone",
    ):
        assert hidden_field not in body


def test_zone_http_manual_returns_no_candidate_pallet_count() -> None:
    client = build_client()

    response = client.post(
        "/quotes/zone-calculate",
        json=base_payload(
            cbm=20,
            weight_kg=100,
            piece_count=36,
            longest_side_cm=300,
            requires_appointment=False,
            handling_units=[],
        ),
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "quote_id",
        "billing_pallets",
        "total_price_usd",
        "sales_note",
        "manual_review_required",
        "public_flags",
    }
    assert body["manual_review_required"] is True
    assert body["billing_pallets"] is None
    assert body["total_price_usd"] is None
    assert body["public_flags"] == ["manual_review_required"]
