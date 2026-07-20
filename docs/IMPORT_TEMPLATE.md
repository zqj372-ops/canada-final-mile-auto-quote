# Import Templates

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

The vendor rate-card importer accepts CSV, XLSX, or XLS files. It validates
structure only in the MVP; database upserts are a later step.

## Zone price matrix

The price-matrix page accepts CSV, XLSX, and XLS files up to 10 MB. Use the
page's **下载当前矩阵模板** action to download a wide-format CSV populated with
the current matrix, or provide either of the following layouts.

### Wide matrix (recommended)

Each source row represents one origin and Zone. Add one or more pallet-price
columns such as `1托`, `2托`, or `3托`.

| 始发仓 | Zone | 燃油附加比例(%) | 1托 | 2托 | 来源备注 | 更新日期 |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| calgary | 1 | 40 | 65.50 | 93.00 | 2026 contract | 2026-07-17 |

### Long detail

Each source row represents one origin, Zone, and billed-pallet count.

| origin | zone | billing_pallets | base_price_usd | fuel_percent | source | last_updated |
| --- | ---: | ---: | ---: | ---: | --- | --- |
| calgary | 1 | 1 | 65.50 | 40 | 2026 contract | 2026-07-17 |

`origin` and `zone` are always required. A long-detail file must contain both
`billing_pallets` and `base_price_usd`; a wide matrix must contain at least one
pallet-price column. `fuel_percent`, `source`, and `last_updated` are optional.

The preview endpoint reports new rows, overwritten rows, fuel changes, warnings,
and row-level validation errors before any data is written. Confirmation applies
price and fuel changes in one transaction. Duplicate price keys or conflicting
fuel percentages for the same origin and Zone are rejected.

Importing a matrix does not change zone price switches. New or previously
unconfigured Zone 1–7 rows are enabled by default, while Zone 8 and above remain
disabled until an administrator explicitly enables that `origin + zone` from
the price-matrix page. Disabled rows keep their imported prices for later reuse.
