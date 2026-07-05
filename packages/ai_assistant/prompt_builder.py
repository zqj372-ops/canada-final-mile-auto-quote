from packages.quote_engine.models import AIQuoteContext, QuoteResult


def build_ai_context(quote_result: QuoteResult) -> AIQuoteContext:
    return AIQuoteContext(
        price_locked=True,
        quote_result={
            "quote_id": quote_result.quote_id,
            "internal_cost_cad": quote_result.internal_cost_cad,
            "suggested_selling_price_cad": quote_result.suggested_selling_price_cad,
            "source_type": quote_result.source_type.value,
            "confidence": quote_result.confidence,
            "matched_rule": quote_result.matched_rule,
            "cost_breakdown": quote_result.cost_breakdown,
            "risk_tags": quote_result.risk_tags,
            "manual_review_required": quote_result.manual_review_required,
        },
    )

