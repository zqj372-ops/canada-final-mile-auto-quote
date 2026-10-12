"""Versioned, conservative eligibility for reviewed one-off prices."""
from datetime import datetime, timezone
from decimal import Decimal

from packages.quote_engine.zone_models import ZoneQuoteRequest


LEARNING_SCHEMA_VERSION = 2


def quote_conditions_from_mapping(values: dict[str, object]) -> dict[str, object]:
    request = ZoneQuoteRequest.model_validate(values)
    data = request.model_dump(mode="python")
    # Postal/city/province are indexed separately; keep every cargo/service fact.
    conditions = {
        key: (str(value.normalize()) if isinstance(value, Decimal) else value)
        for key, value in data.items()
        if key not in {"postal_code", "city", "province"}
    }
    conditions["address_line"] = " ".join((request.address_line or "").upper().split())
    conditions["schema_version"] = LEARNING_SCHEMA_VERSION
    return conditions


def valid_price_terms(terms: object, *, now: datetime | None = None) -> bool:
    if not isinstance(terms, dict):
        return False
    try:
        start = datetime.fromisoformat(str(terms["valid_from"]))
        end = datetime.fromisoformat(str(terms["valid_until"]))
        if start.tzinfo is None or end.tzinfo is None:
            return False
        return bool(
            terms.get("supplier") and terms.get("source_reference")
            and terms.get("price_type") == "all_in" and terms.get("currency") == "USD"
            and start <= (now or datetime.now(timezone.utc)) < end
        )
    except (KeyError, ValueError, TypeError):
        return False


def quote_conditions_match(values: object, request: ZoneQuoteRequest) -> bool:
    if not isinstance(values, dict) or not valid_price_terms(values.get("price_terms")):
        return False
    expected = quote_conditions_from_mapping(request.model_dump(mode="json"))
    stored = {key: value for key, value in values.items() if key != "price_terms"}
    return bool(expected["address_line"]) and stored == expected
