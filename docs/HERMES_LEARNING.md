# Hermes 自学习候选机制

Hermes 是报价经验学习层，不是报价引擎。它只能从人工复核结果中生成候选建议，不能直接计算、修改或放行价格。
旧的同步 Agent 纠错能力已降级为“LLM 辅助建议”，不再接入主报价链路。

## 核心边界

- AI/Hermes 不直接报价。
- Hermes 不直接修改 `zone_price_matrix`。
- Hermes 不覆盖正常 `zone_matrix` 成功报价。
- 人工任务 resolved 后只生成 `pending_review` 候选。
- 只有后台 operator/admin 批准后，候选才会发布为 `learned_quote_rules.active`。
- 学习规则只在原始 Quote Engine 返回 `manual_required` 后尝试复用。
- 搜索和地图结果只能确认地址情况，不能作为价格来源。
- `hermes_diagnostic_queue` 是 Hermes Agent 的只读输入队列；Agent 建议不能直接改变报价结果。

## 数据流

```text
客户询价
  -> AI/规则解析字段
  -> Zone Quote Engine 确定性报价
  -> 成功则返回 zone_matrix
  -> 成功/失败都写入 hermes_diagnostic_queue
  -> Hermes Agent 只读诊断包并输出建议
  -> 未命中则 manual_required + manual_quote_tasks
  -> 运营人工处理并填写 resolved_price_usd
  -> Hermes 生成 hermes_learning_candidates.pending_review
  -> 后台审核
  -> 批准后写入 learned_quote_rules.active
  -> 后续同类 manual_required 可复用学习规则
```

诊断包包含原始输入、解析结果、邮编、城市、省份、Zone 命中、价格矩阵、失败原因、
相邻 FSA、历史人工确认和私有地址参考小上下文。报价接口不会等待 Hermes Agent，
避免外部模型慢响应影响销售前台。

## 候选状态

- `pending_review`: 待审核，默认状态，不参与报价。
- `approved`: 已批准，并已发布为学习规则。
- `rejected`: 已拒绝，不参与报价。

## 发布后的复用条件

学习规则必须满足：

- `status = active`
- `billing_pallets` 一致
- `postal_code` 精确一致，或 `postal_prefix + city + province` 一致

复用结果的 `source_type` 为 `learned_manual_quote`，并保留风险标签：

- `learned_quote_reused`
- `learned_from_manual_task`

## 操作建议

- 单票价格异常但没有可复用规律：拒绝候选或保持待审。
- 同一 FSA/城市/托数多次人工结果一致：批准候选。
- 已发布规则发现不准：在 Hermes 页面禁用对应学习规则。
- 需要长期正式化的规则：后续再人工迁移到 `zone_lookup_rules` 或 `zone_price_matrix`，不要由 Hermes 自动写入。

## 随机邮编命中测试

可以用脚本让服务侧诊断 Agent 随机抽样邮编，批量跑 Quote Engine，整理哪些区域依赖模糊命中、哪些区域缺 Zone 或价格矩阵。

```bash
python scripts/postal_hit_test_agent.py \
  --sample-size 5000 \
  --profiles 1p \
  --persist-diagnostics \
  --persist-only manual
```

输出：

- `outputs/postal_hit_tests/postal_hit_test_*.json`
- `outputs/postal_hit_tests/postal_hit_test_*.md`

规则边界：

- 脚本不会修改 `zone_price_matrix`。
- 脚本不会发布 `learned_quote_rules`。
- `--persist-diagnostics --persist-only manual` 只把无法自动报价的样本写入 `hermes_diagnostic_queue`，避免后台被大量成功回退样本刷屏。
- 成功但依赖模糊回退的样本仍会进入报告的规则整理建议。
- 真正学习规则仍然必须来自人工任务 resolved 后生成的候选，并经后台审核批准。
