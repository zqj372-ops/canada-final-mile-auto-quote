from datetime import date

from tests.api.test_fcl_quotes import SALES_KEY, build_client, confirmed_draft


def test_fcl_quote_moves_through_sales_send_and_customer_outcome() -> None:
    client, _ = build_client()
    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={"confirmed_fields": confirmed_draft(), "auto_submit_when_complete": True},
    )
    assert response.status_code == 200
    record = client.get("/quotes/sales-records", headers={"X-API-Key": SALES_KEY}).json()[0]
    assert record["workflow_status"] == "ready_to_send"
    assert "copy_customer_reply" in record["allowed_actions"]

    sent = client.post(
        f"/quotes/sales-records/{record['id']}/mark-sent",
        headers={"X-API-Key": SALES_KEY},
        json={"channel": "wechat", "note": "已发送客户"},
    )
    assert sent.status_code == 200
    assert sent.json()["workflow_status"] == "sent"

    outcome = client.post(
        f"/quotes/sales-records/{record['id']}/outcome",
        headers={"X-API-Key": SALES_KEY},
        json={"outcome": "accepted", "note": "客户确认"},
    )
    assert outcome.status_code == 200
    assert outcome.json()["workflow_status"] == "accepted"
    assert [event["to_status"] for event in outcome.json()["timeline"]][-3:] == [
        "ready_to_send",
        "sent",
        "accepted",
    ]


def test_manual_task_resolve_writes_public_snapshot_and_record_atomically() -> None:
    client, _ = build_client(rate_card_status="draft")
    response = client.post(
        "/quotes/fcl-auto-quote",
        headers={"X-API-Key": SALES_KEY},
        json={"confirmed_fields": confirmed_draft(), "auto_submit_when_complete": True},
    )
    assert response.status_code == 200
    record = client.get("/quotes/sales-records", headers={"X-API-Key": SALES_KEY}).json()[0]
    task = client.get("/quotes/manual-tasks", headers={"X-API-Key": "fcl_admin_key"}).json()[0]

    claim = client.post(
        f"/quotes/manual-tasks/{task['id']}/claim",
        headers={"X-API-Key": "fcl_admin_key"},
        json={},
    )
    assert claim.status_code == 200
    resolved = client.post(
        f"/quotes/manual-tasks/{task['id']}/resolve",
        headers={"X-API-Key": "fcl_admin_key"},
        json={
            "fee_items": [{"item_name": "海运费", "amount": "1300.00", "currency": "USD", "quantity": 1}],
            "totals_by_currency": {"USD": "1300.00"},
            "settlement_currency": "USD",
            "converted_total": "1300.00",
            "valid_until": date.today().isoformat(),
            "public_note": "人工确认报价",
            "customer_terms": ["有效期内有效"],
            "customer_reply": "确认报价 USD 1300.00。",
            "internal_note": "已核对供应商费率",
        },
    )
    assert resolved.status_code == 200
    detail = client.get(f"/quotes/sales-records/{record['id']}", headers={"X-API-Key": SALES_KEY})
    assert detail.status_code == 200
    body = detail.json()
    assert body["workflow_status"] == "ready_to_send"
    assert body["public_snapshot"]["totals_by_currency"] == {"USD": "1300.00"}
    assert "供应商" not in detail.text
    assert "internal_note" not in detail.text
