from decimal import Decimal, InvalidOperation
import re

from pydantic import BaseModel

from packages.quote_engine.models import AIQuoteContext
from packages.quote_engine.zone_models import ZoneQuoteResult


MONEY_RE = re.compile(
    r"(?:(?:USD|US\$|CAD|CA\$|\$)\s*(\d+(?:\.\d{1,2})?)|(\d+(?:\.\d{1,2})?)\s*(?:USD|US\$|CAD|CA\$))",
    re.IGNORECASE,
)


class GuardResult(BaseModel):
    allowed: bool
    reason: str | None = None


def validate_ai_output(context: AIQuoteContext, output_text: str) -> GuardResult:
    if not context.price_locked:
        return GuardResult(allowed=False, reason="AI context must be price_locked.")

    allowed_amounts = _allowed_money_amounts(context)
    generated_amounts = _extract_money_amounts(output_text)

    for amount in generated_amounts:
        if amount not in allowed_amounts:
            return GuardResult(
                allowed=False,
                reason=f"AI output mentioned {amount} CAD, which is not in quote_result.",
            )

    return GuardResult(allowed=True)


def validate_zone_ai_output(quote_result: ZoneQuoteResult, output_text: str) -> GuardResult:
    generated_amounts = _extract_money_amounts(output_text)
    if quote_result.manual_review_required and generated_amounts:
        return GuardResult(
            allowed=False,
            reason="AI output mentioned a definite amount while manual review is required.",
        )

    allowed_amounts = _allowed_zone_money_amounts(quote_result)
    for amount in generated_amounts:
        if amount not in allowed_amounts:
            return GuardResult(
                allowed=False,
                reason=f"AI output mentioned {amount} USD, which is not in quote_result.",
            )

    return GuardResult(allowed=True)


def _allowed_money_amounts(context: AIQuoteContext) -> set[Decimal]:
    values: set[Decimal] = set()
    quote_result = context.quote_result

    for key in ("internal_cost_cad", "suggested_selling_price_cad", "margin_cad"):
        _add_decimal(values, quote_result.get(key))

    breakdown = quote_result.get("cost_breakdown")
    if isinstance(breakdown, dict):
        for value in breakdown.values():
            _add_decimal(values, value)

    return values


def _allowed_zone_money_amounts(quote_result: ZoneQuoteResult) -> set[Decimal]:
    values: set[Decimal] = set()
    for value in (
        quote_result.total_price_usd,
        quote_result.base_price_usd,
        quote_result.fuel_usd,
    ):
        _add_decimal(values, value)
    for value in quote_result.accessorials.values():
        _add_decimal(values, value)
    return values


def _extract_money_amounts(output_text: str) -> set[Decimal]:
    amounts: set[Decimal] = set()
    for match in MONEY_RE.findall(output_text):
        raw = match[0] or match[1]
        _add_decimal(amounts, raw)
    return amounts


def _add_decimal(values: set[Decimal], value: object) -> None:
    if value is None:
        return
    try:
        values.add(Decimal(str(value)).quantize(Decimal("0.01")))
    except (InvalidOperation, ValueError):
        return
