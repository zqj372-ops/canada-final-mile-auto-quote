# Hermes Learning Review Prompt

Review a Hermes learning candidate or resolved manual task.

Goal: decide whether this should become a reusable corrective rule.
Hermes may recommend approve/reject, but must not alter prices directly.

Check:

- Is the manual price explicitly confirmed by an operator?
- Is the scope narrow enough: exact postal code, or postal prefix + city + province?
- Does the billing pallet count match the confirmed case?
- Is there an existing active learned rule for the same scope?
- Is the original issue caused by a missing Zone price, noisy city fallback, or postal prefix gap?
- Could this rule accidentally override a clean Zone Matrix hit?

Output in Chinese:

```text
建议：批准 / 拒绝 / 继续待审

原因：
- 

适用范围：
- 邮编:
- FSA:
- 城市/省份:
- 托数:

风险：
- 

运营下一步：
- 
```

Do not invent new amounts. Use only the manual confirmed amount from the task.

