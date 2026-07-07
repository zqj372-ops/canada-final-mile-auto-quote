# Quote Incident Review Prompt

Use this when a quote looks wrong or went to `manual_required`.

First run:

```bash
ops/hermes/scripts/quote_debug_snapshot.sh <quote_id>
```

If there is no quote_id, use:

```bash
ops/hermes/scripts/check_zone_match.sh <postal_prefix> <city> <province>
```

Explain in Chinese:

```text
问题判断：
- 正常命中 / 错误回退 / 价格矩阵缺价 / 需要人工确认

命中路径：
- Postal lookup:
- Zone rule:
- Price matrix:
- Learned rule:

为什么会这样：
- 

是否可以自动纠错：
- 可以 / 不建议 / 需要人工确认

建议动作：
1.
2.
```

Never produce a customer-facing price unless the deterministic quote result or
an approved learned rule already contains that exact price.

