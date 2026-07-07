# Zone Match Debug Prompt

Use this to debug city, FSA, province, origin, and Zone matching.

Run:

```bash
ops/hermes/scripts/check_zone_match.sh <postal_prefix> <city> <province>
```

When reviewing results, check:

- Postal-code preferred city/province record count.
- Exact FSA Zone rule.
- Same city/province Zone rules.
- Same first two postal-prefix characters.
- Same first postal-prefix character.
- Price rows for the selected origin/Zone.
- Any active learned quote rule with the same scope.

Summarize in Chinese:

```text
推荐判断：
- 

数据证据：
- 

如果要修复：
- 添加/调整 Zone rule:
- 添加/调整 price matrix:
- 是否应走 Hermes learned rule:
```

Do not hardcode a one-off zone unless the business table supports it.

