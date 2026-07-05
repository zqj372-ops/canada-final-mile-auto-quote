# AI Guardrails

## Hard Rules

- AI must not decide quote amounts.
- AI must not read full Excel workbooks or complete rate cards.
- AI must not invent fees, market rates, distance prices, or carrier prices.
- AI receives only a small price-locked JSON context.
- AI output is blocked if it mentions an amount not present in `quote_result`.

## Allowed Actions

- Explain the quote.
- Summarize risk tags.
- Draft sales notes.
- Warn that manual review is required.

## Forbidden Actions

- Change `internal_cost_cad`.
- Change `suggested_selling_price_cad`.
- Add unverified fees.
- Present a price when `manual_review_required=true`.

## Example Context

```json
{
  "price_locked": true,
  "quote_result": {
    "internal_cost_cad": 268,
    "suggested_selling_price_cad": 360,
    "source_type": "fsa",
    "confidence": 80,
    "risk_tags": ["dock_unknown", "appointment_required"]
  },
  "allowed_actions": ["explain", "summarize", "warn_risk"],
  "forbidden_actions": ["change_price", "invent_fee", "invent_market_rate"]
}
```

