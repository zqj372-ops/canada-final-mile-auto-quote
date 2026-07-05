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

## Zone Quote Engine

The Canada final-mile MVP uses the Zone quote path as the primary pricing path:

1. Normalize the full postal code and extract FSA.
2. Optionally look up preferred city from `postal_code_city_lookup`.
3. Resolve `postal_prefix + city + province` to a unique `zone_lookup_rules` row.
4. Override stale BC origins to `calgary` and add `stale_origin_overridden`.
5. Calculate billing pallets with the deterministic pallet rules.
6. Look up `origin + zone + billing_pallets` in `zone_price_matrix`.
7. Add fuel and confirmed accessorials.

If any lookup is ambiguous, missing, or split-record unsafe, the engine returns
`manual_required`.

Fuel and accessorials:

- Fuel is `base_price_usd * 35%`.
- Residential/private/rural residential: `+50 USD`.
- Liftgate: `+50 USD` only when requested.
- Pallet jack: `+50 USD` only when requested.
- Appointment: `+50 USD` only when requested.
- Detention: first 30 minutes free, then `35 USD` per started half hour.
