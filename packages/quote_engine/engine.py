from packages.quote_engine.matching import find_best_rule
from packages.quote_engine.models import QuoteCalculationRequest, QuoteResult
from packages.quote_engine.pricing import calculate_quote


class QuoteEngine:
    """Deterministic quote engine. AI code must not call pricing logic directly."""

    def quote(self, request: QuoteCalculationRequest) -> QuoteResult:
        match = find_best_rule(request.shipment, request.rate_rules)
        return calculate_quote(request.shipment, match)

