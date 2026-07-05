# Data Schema

## Rate Rule Fields

| Field | Purpose |
| --- | --- |
| `origin_warehouse` | Shipping origin, such as Toronto or Calgary. |
| `vendor_name` | Carrier or vendor rate source. |
| `province` | Normalized Canadian province code. |
| `city` | Normalized destination city. |
| `fsa` | First three characters of the Canadian postal code. |
| `postal_code` | Full normalized Canadian postal code. |
| `pallet_min` | Minimum billable pallet count. |
| `pallet_max` | Maximum billable pallet count. |
| `weight_min_kg` | Optional minimum shipment weight. |
| `weight_max_kg` | Optional maximum shipment weight. |
| `base_cost_cad` | Base internal cost from the structured price source. |
| `fuel_percent` | Fuel surcharge percent applied to base cost. |
| `appointment_fee_cad` | Appointment fee. |
| `liftgate_fee_cad` | Liftgate fee. |
| `residential_fee_cad` | Residential delivery fee. |
| `limited_access_fee_cad` | Limited access fee. |
| `remote_fee_cad` | Remote area fee. |
| `effective_from` | Rule start date. |
| `effective_to` | Rule end date. |
| `status` | Rule status, usually `active` or `inactive`. |

## Source Materials

Existing reference documents and raw lookup tables are stored under
`reference/canada-final-mile/`. Runtime imports should normalize those materials
into database tables before the quote engine uses them.

## Zone Quote Tables

### `postal_code_city_lookup`

| Field | Purpose |
| --- | --- |
| `postal_code` | Normalized full Canadian postal code, such as `L4K 2N2`. |
| `preferred_city` | Preferred city from the postal-code lookup source. |
| `province` | Province inferred from the postal-code initial. |

### `zone_lookup_rules`

| Field | Purpose |
| --- | --- |
| `postal_prefix` | FSA / first three postal-code characters. |
| `city` | Destination city used to disambiguate split records. |
| `province` | Province code used to disambiguate split records. |
| `origin` | Normalized quote origin: `toronto` or `calgary`. |
| `zone` | Carrier zone from the lookup table. |
| `match_level` | Source match level, such as L1/L2/demo. |
| `note` | Source notes and edge-case context. |

### `zone_price_matrix`

| Field | Purpose |
| --- | --- |
| `origin` | Normalized quote origin. |
| `zone` | Zone number. |
| `billing_pallets` | Billable pallet count used for lookup. |
| `base_price_usd` | Base price from the Zone matrix. |
| `source` | Source label for audit. |
| `last_updated` | Source update timestamp/date. |

Zone prices are USD. Missing matrix prices must return `manual_required`; the
engine must not estimate by multiplying a pallet count by a unit price.

### `quote_rule_config`

| Field | Purpose |
| --- | --- |
| `key` | Config key such as `fuel_percent` or `liftgate_fee_usd`. |
| `value` | String value parsed by the configuration repository. |
| `description` | Human-readable config note. |

Supported Zone pricing config keys:

- `fuel_percent`
- `residential_fee_usd`
- `liftgate_fee_usd`
- `pallet_jack_fee_usd`
- `appointment_fee_usd`
- `detention_half_hour_fee_usd`
- `detention_free_minutes`

When a key is missing or invalid, the engine uses the default `ZonePricingConfig`
value.

### `quote_audit_logs`

Stores one record for every `/quotes/zone-calculate` attempt, including manual
review outcomes. `request_json` and `result_json` preserve the exact API payload
and deterministic quote result for replay and support.

### `manual_quote_tasks`

Stores workbench tasks created automatically when a Zone quote returns
`manual_required`. Operations can assign, resolve, and annotate these records
without changing the original deterministic quote result.
