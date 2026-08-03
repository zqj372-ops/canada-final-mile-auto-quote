import pytest
from pydantic import ValidationError

from apps.api.services.fcl_quote_service import FCLAutoQuoteRequest


def valid_payload() -> dict[str, object]:
    return {
        "customer_id": 7,
        "confirmed_fields": {
            "pol": "CNSHA",
            "pod": "CAVAN",
            "containers": [{"container_type": "40HQ", "quantity": 1}],
            "target_etd": "2026-08-10",
        },
    }


def test_fcl_request_requires_customer_and_only_structured_fields():
    payload = FCLAutoQuoteRequest.model_validate(valid_payload())
    assert payload.customer_id == 7
    assert payload.confirmed_fields.pol == "CNSHA"

    with pytest.raises(ValidationError):
        FCLAutoQuoteRequest.model_validate({"confirmed_fields": {}})


@pytest.mark.parametrize(
    "field",
    ["raw_message", "ai_config_id", "auto_submit_when_complete", "confidence", "extraction_notes", "service_stages"],
)
def test_fcl_form_rejects_extraction_and_legacy_fields(field):
    invalid = valid_payload()
    invalid[field] = "legacy"
    with pytest.raises(ValidationError):
        FCLAutoQuoteRequest.model_validate(invalid)


@pytest.mark.parametrize("field", ["contact", "confidence", "extraction_notes", "service_stages"])
def test_nested_fcl_form_rejects_legacy_fields(field):
    invalid = valid_payload()
    invalid["confirmed_fields"] = {field: "legacy"}
    with pytest.raises(ValidationError):
        FCLAutoQuoteRequest.model_validate(invalid)
