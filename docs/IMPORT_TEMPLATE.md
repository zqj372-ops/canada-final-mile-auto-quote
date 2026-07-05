# Import Template

Vendor rate card imports must include these columns after normalization:

| Column |
| --- |
| `origin_warehouse` |
| `vendor_name` |
| `province` |
| `city` |
| `fsa` |
| `postal_code` |
| `pallet_min` |
| `pallet_max` |
| `weight_min_kg` |
| `weight_max_kg` |
| `base_cost_cad` |
| `fuel_percent` |
| `appointment_fee_cad` |
| `liftgate_fee_cad` |
| `residential_fee_cad` |
| `limited_access_fee_cad` |
| `remote_fee_cad` |
| `effective_from` |
| `effective_to` |
| `status` |

The importer may accept CSV, XLSX, or XLS files. It validates structure only in
the MVP; database upserts are a later step.

