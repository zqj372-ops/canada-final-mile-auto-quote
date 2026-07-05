# Reference Index

This repository keeps the Canada final-mile quote source materials under
`reference/canada-final-mile/`.

## Runtime Entry Points

- `SOP_QUICK.md` - primary operating SOP for real-time quoting.
- `RULES.yaml` - machine-readable rule parameters used with the SOP.
- `QUOTE_TEMPLATE.md` - formal and short quote output templates.
- `EDGE_CASES.md` - exception handling for ambiguous postal/zone/address cases.

## Data Tables

- `canadapostalcodeslist(1).json` - Canadian postal code to preferred city lookup.
- `Zone 邮编前缀 城市 省份 始发仓 查询表.json` - FSA/city/province to zone lookup table.
- `Zone 票价表（查表价格）.json` - origin, zone, and billing pallet price table.

## Background And History

- `物流报价SOP.md` - broader logistics quote SOP.
- `加拿大尾程派送报价规则.md` - archived Canada final-mile quote rules.
- `Canadian postal codes and the preferred city name for each.md` - postal-code data notes.
- `CHANGELOG.md` - rule and data changes.

## Implementation Notes

- Quote base prices must come from the price table.
- Do not invent base prices through per-pallet, mileage, or linear zone extrapolation.
- Keep the source materials together unless `RULES.yaml` data file paths are updated at the same time.
