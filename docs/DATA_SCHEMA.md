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

