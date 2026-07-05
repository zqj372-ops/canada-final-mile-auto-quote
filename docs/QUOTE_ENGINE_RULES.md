# Quote Engine Rules

## Boundary

The quote engine is the only component allowed to calculate prices. AI can
explain the final `quote_result`, but it cannot modify price fields.

## Matching Priority

1. `history_exact_address`
2. `postal_code`
3. `fsa`
4. `city`
5. `rate_card`
6. `distance_fallback`
7. `manual_required`

`distance_fallback` is reserved for a future deterministic distance service. In
the current MVP it must not fabricate a price.

## Required Output Fields

- `quote_id`
- `source_type`
- `confidence`
- `matched_rule`
- `internal_cost_cad`
- `suggested_selling_price_cad`
- `margin_cad`
- `margin_percent`
- `cost_breakdown`
- `risk_tags`
- `manual_review_required`
- `sales_note`
- `internal_note`

## Manual Review

When no deterministic rule matches, the engine returns `manual_required` with
`manual_review_required=true` and no price. Downstream systems must not expose a
price to customers in this state.

