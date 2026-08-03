# Quote Inputs and Deterministic Engines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让加拿大末端货物数据由结构化分项重新计算，让 FCL 只接受结构化表单，并修复所有会产生错误自动报价的精度、作用域、日期、冲突和默认配置问题。

**Architecture:** 新增可复用的确定性货物指标模块；加拿大末端把识别结果适配为该模块的输入，FCL 使用自身类型但遵守相同计算契约。FCL API 删除文本提取路径，报价服务只读取已发布配置；引擎在任何不唯一或不完整情形下 fail closed。

**Tech Stack:** Python `Decimal`、Pydantic 2、Pytest、FastAPI、React、TypeScript、Vitest、Testing Library。

---

## Task 1: 锁定加拿大末端货物计算契约

**Files:**

- Create: `packages/quote_engine/cargo_metrics.py`
- Create: `tests/quote-engine/test_cargo_metrics.py`
- Modify: `packages/ai_assistant/quote_extractor.py`
- Modify: `tests/ai-assistant/test_quote_extractor.py`

- [ ] 先写 `test_cargo_metrics.py`，覆盖：
  - 两托盘 `120×100×125 cm`；
  - 单件重量列表 `[785, 800]`；
  - 总体积 `3.000 m³`；
  - 总重量 `1585.00 kg`；
  - 密度 `528.33 kg/m³`；
  - 最大单件 `800.00 kg`；
  - 英寸、米、磅和克的单位换算；
  - 数量与重量列表长度不一致时产生阻断错误；
  - `unit_weight`、`piece_weights`、`line_total_weight` 三种输入模式分别规范化为唯一 `weight_mode`；
  - 同一行同时提供两种或三种重量证据时，只有数学结果完全一致才可接受并规范化，任一不一致都产生 `line_weight_evidence_conflict`；
  - 数量大于 1 且只有 `line_total_weight` 时可以计入总重量，但不能反推平均单件重量或最大单件重量，并产生阻断自动报价的 `max_single_weight_unknown`；
  - 数量等于 1 且只有 `line_total_weight` 时，最大单件重量等于该行总重量；
  - 总体积为零时不计算密度并产生阻断错误；
  - 只有声明总重量/总体积而没有完整货物行时产生阻断错误；
  - 声明合计与分项计算冲突时保留两者并标记冲突。
- [ ] 失败测试使用精确断言：

```python
assert result.total_volume_cbm == Decimal("3.000")
assert result.total_weight_kg == Decimal("1585.00")
assert result.billing_density_kg_per_cbm == Decimal("528.33")
assert result.max_single_weight_kg == Decimal("800.00")
assert result.blocking_conflicts == []
```

- [ ] 运行并确认模块不存在而失败。

```bash
pytest -q tests/quote-engine/test_cargo_metrics.py
```

- [ ] 实现不可变输入和结果模型：

```python
class CargoMetricItem(BaseModel):
    model_config = ConfigDict(extra="forbid")
    quantity: int = Field(gt=0)
    length: Decimal = Field(gt=0)
    width: Decimal = Field(gt=0)
    height: Decimal = Field(gt=0)
    dimension_unit: Literal["mm", "cm", "m", "in"] = "cm"
    unit_weight: Decimal | None = Field(default=None, gt=0)
    piece_weights: list[Decimal] = Field(default_factory=list)
    line_total_weight: Decimal | None = Field(default=None, gt=0)
    weight_unit: Literal["g", "kg", "lb"] = "kg"

class CargoMetrics(BaseModel):
    items: list[dict[str, str | int | list[str]]]
    total_piece_count: int
    total_volume_cbm: Decimal
    total_weight_kg: Decimal
    billing_density_kg_per_cbm: Decimal | None
    max_single_weight_kg: Decimal | None
    declared_total_volume_cbm: Decimal | None
    declared_total_weight_kg: Decimal | None
    blocking_conflicts: list[str]
    formula_version: Literal["cargo-metrics-v1"] = "cargo-metrics-v1"
```

- [ ] 在 `CargoMetricItem` 的 `model_validator` 校验每种证据的结构：`piece_weights` 非空时长度必须等于数量，所有重量必须为正，至少存在一种重量证据；随后由计算器把 `unit_weight`、`piece_weights`、`line_total_weight` 归一成互斥的规范化 `weight_mode` 和行总重量。
- [ ] 多种重量证据可同时作为原始证据进入校验，但换算到 kg 后必须数学一致：`unit_weight × quantity == sum(piece_weights) == line_total_weight`（仅比较实际提供项，使用 `Decimal`）；一致时按 `piece_weights > unit_weight > line_total_weight` 保留最有信息量的规范化模式，不一致时保留各证据并加入 `line_weight_evidence_conflict`，绝不能选一个值继续自动报价。
- [ ] 只有 `line_total_weight` 且数量大于 1 时，可以用于权威总重量加总，但 `max_single_weight_kg` 必须为 `None` 并加入 `max_single_weight_unknown`；禁止用行总重除以数量假设平均单重。数量等于 1 时可把行总重作为最大单件重量。
- [ ] 声明合计只进入证据和冲突字段，不能成为 `total_weight_kg` 或 `total_volume_cbm` 的计算输入；缺少完整分项、存在冲突或仅有销售确认都不能解除自动报价阻断。
- [ ] 尺寸先转米，重量先转 kg；内部不提前舍入，输出体积保留 3 位、重量 2 位、密度 2 位。
- [ ] 扩展 `ExtractedCargoItem` 支持 `unit_weight_kg`、`piece_weights_kg` 和 `line_total_weight_kg` 三种证据；确定性重量加法表达式 `785+800=1585` 映射为两个真实单件重量，并把 `1585` 作为一致性证据，不把 `792.5` 平均值当最大单件。
- [ ] 运行货物指标和提取器测试，预期通过。
- [ ] 提交。

```bash
git add packages/quote_engine/cargo_metrics.py packages/ai_assistant/quote_extractor.py tests/quote-engine/test_cargo_metrics.py tests/ai-assistant/test_quote_extractor.py
git commit -m "fix(cargo): derive authoritative metrics from item rows"
```

## Task 2: 将权威货物计算接入加拿大末端 API

**Files:**

- Modify: `apps/api/services/ai_quote_service.py`
- Modify: `apps/api/routes/ai_quotes.py`
- Modify: `packages/quote_engine/zone_models.py`
- Modify: `tests/api/test_ai_auto_quote.py`
- Create: `tests/api/test_ai_cargo_calculation.py`

- [ ] 先写 API 测试，提交截图示例文本，断言响应包含独立 `cargo_calculation`，且报价请求使用计算值而不是原文声明值。
- [ ] 测试加拿大末端请求缺少 `customer_id` 返回 `422`；传入当前销售可访问客户后，草稿/记录保存该 `customer_id`，但本阶段不复制可变客户名称充当历史快照。
- [ ] 测试原文声明 `1500 kg`、分项为 `785+800` 时：响应显示声明 `1500`、计算 `1585` 和冲突；未显式确认冲突前不调用 Zone Quote Engine，进入可修正状态或人工处理。
- [ ] 对 Zone Quote Engine 使用严格 mock，分别测试“冲突首次返回后直接重试”和“提交冲突确认后重试”；两条路径调用次数都必须为 `0`。冲突确认只记录证据，永远不是放行开关。
- [ ] 测试持久化失败时接口返回错误且不会吞异常后返回 200。
- [ ] 运行并确认 `cargo_calculation` 缺失或旧逻辑失败。

```bash
pytest -q tests/api/test_ai_cargo_calculation.py tests/api/test_ai_auto_quote.py
```

- [ ] 加拿大末端正式请求模型用 `extra="forbid"` 声明必填正整数 `customer_id`；服务端按当前销售客户作用域验证客户可见性，并把 `customer_id` 持久化到报价草稿/记录。客户名称不可变快照由总计划的计划 3 在锁定报价版本时写入。
- [ ] 在 `AIAutoQuoteResponse` 增加类型化 `cargo_calculation: CargoMetrics | None`，不使用 `object`。
- [ ] 提取完成后立即用 `cargo_items` 计算权威结果；仅当 `blocking_conflicts` 为空时才构造并调用 Zone Quote Engine，`cbm`、`weight_kg`、`piece_count` 和 `longest_side_cm` 从计算结果取得。存在冲突时，无论请求是在确认前还是确认后到达，都必须在引擎调用之前返回可修正/人工状态。
- [ ] 冲突响应返回中文代码映射：
  - `declared_total_weight_conflict` → `原文总重量与货物明细计算结果不一致，请确认货物明细。`
  - `declared_total_volume_conflict` → `原文总体积与尺寸计算结果不一致，请确认尺寸和数量。`
  - `piece_weight_count_mismatch` → `单件重量数量与货物数量不一致。`
- [ ] 删除 `_record_sales_response` 和 `_record_ai_review_task` 中吞掉数据库异常的 `try/except Exception`；本计划先让异常冒泡并回滚，计划 3 再把记录、版本、任务和事件统一进一个应用事务。
- [ ] 运行定向测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/services/ai_quote_service.py apps/api/routes/ai_quotes.py packages/quote_engine/zone_models.py tests/api/test_ai_auto_quote.py tests/api/test_ai_cargo_calculation.py
git commit -m "fix(final-mile): price from server-calculated cargo metrics"
```

## Task 3: 在销售前台展示并编辑计算货物行

**Files:**

- Modify: `apps/web/src/components/ParsedCargoTable.tsx`
- Modify: `apps/web/src/components/AiQuoteInputPanel.tsx`
- Modify: `apps/web/src/pages/QuotePage.tsx`
- Modify: `apps/web/src/api/salesQuotes.ts`
- Modify: `apps/web/src/domain/quotes.ts`
- Create: `apps/web/src/features/final-mile/cargoMetrics.ts`
- Create: `apps/web/src/features/final-mile/CargoMetricsSummary.tsx`
- Create: `apps/web/src/features/final-mile/CargoMetricsSummary.test.tsx`
- Create: `apps/web/src/features/final-mile/cargoInvalidation.test.ts`
- Reuse: `apps/web/src/features/customers/CustomerNameField.tsx`

- [ ] 先写组件测试：未选择客户时不能提交；选择计划 1 `CustomerNameField` 返回的 `customer_id` 后，请求只携带该 ID 和报价字段；输入两个托盘和两个不同重量，断言页面显示公式和四个正确指标。
- [ ] 写客户名称生命周期测试：本阶段前端只提交 `customer_id`，不把当前名称复制进可编辑报价结果；计划 3 锁定 V1/V2 时再冻结 `QuoteVersion.customer_name`，后续客户重命名不改变历史版本。
- [ ] 先写失效测试：编辑数量、尺寸、重量或重量列表后，旧 `quote_result`、确认标记和 PDF 文档引用立即清空；只编辑非定价 UI 展开状态不失效。
- [ ] 运行并确认旧组件只展示识别结果而失败。

```bash
cd apps/web
npm test -- --run src/features/final-mile/CargoMetricsSummary.test.tsx src/features/final-mile/cargoInvalidation.test.ts
```

- [ ] `cargoMetrics.ts` 只做前端即时预览，使用十进制字符串和明确换算；提交后以 API 返回的 `cargo_calculation` 覆盖显示。
- [ ] `ParsedCargoTable` 支持 `unit_weight`、`piece_weights` 和 `line_total_weight` 三种重量证据；当一行数量大于 1 且重量不同，展开 `piece_weights_kg` 编辑器；只有行总重时明确显示“无法得出最大单件”，不得展示平均值冒充单重。
- [ ] 加拿大末端客户选择必须复用计划 1 的 `CustomerNameField`，只显示/创建名称并提交必填 `customer_id`；不得在本页另造联系人或自由文本客户字段。
- [ ] 并列显示“原文声明”和“系统计算”；冲突使用警告卡并阻止自动报价。销售确认不能绕过；只有修正识别错误并使完整货物行重新计算后无冲突，或转入人工复核，才能继续。
- [ ] `CargoMetricsSummary` 显示示例形式的公式，不把原文 `785公斤+800kg=1585kgs` 原样作为最终数据。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/components/ParsedCargoTable.tsx apps/web/src/components/AiQuoteInputPanel.tsx apps/web/src/pages/QuotePage.tsx apps/web/src/api/salesQuotes.ts apps/web/src/domain/quotes.ts apps/web/src/features/final-mile
git commit -m "feat(web): show calculated final-mile cargo metrics"
```

## Task 4: 将 FCL 公共契约收窄为结构化表单

**Files:**

- Modify: `apps/api/services/fcl_quote_service.py`
- Modify: `apps/api/routes/fcl_quotes.py`
- Modify: `packages/quote_engine/fcl.py`
- Modify: `tests/api/test_fcl_quotes.py`
- Modify: `tests/api/test_fcl_workflow.py`
- Create: `tests/api/test_fcl_structured_contract.py`

- [ ] 先写契约测试：请求体只接受 `confirmed_fields` 和 `customer_id`，幂等键只通过 `Idempotency-Key` header 传入；发送 `raw_message`、`ai_config_id`、`auto_submit_when_complete`、`confidence`、`extraction_notes` 或请求体 `idempotency_key` 返回 `422`。
- [ ] 对 `FCLAutoQuoteRequest`、`FCLQuoteDraft` 以及所有嵌套柜型、货物和报关模型逐层发送额外字段，断言全部返回 `422`；不能只在最外层 `extra="forbid"`。
- [ ] 对正式 API 打补丁监控 `extract_fcl_draft` 和 AI 客户端，确认永不调用。
- [ ] 测试无已发布配置时返回人工复核结果 `no_published_config`，且 `config_version` 不得为 0 自动报价。
- [ ] 运行并确认旧请求模型接受文本字段或使用默认配置而失败。

```bash
pytest -q tests/api/test_fcl_structured_contract.py tests/api/test_fcl_quotes.py tests/api/test_fcl_workflow.py
```

- [ ] 将正式请求模型固定为：

```python
class FCLAutoQuoteRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    customer_id: int
    confirmed_fields: FCLQuoteDraft
```

- [ ] 路由使用 `Header(alias="Idempotency-Key", min_length=8, max_length=128)` 读取幂等键并传给应用服务，不把它混入业务表单快照。

- [ ] `FCLQuoteDraft` 及所有嵌套输入模型显式配置 `ConfigDict(extra="forbid", str_strip_whitespace=True)`；删除公开字段 `contact`、`confidence`、`extraction_notes` 和 `service_stages`。如果历史快照读取需要兼容，只在与正式路由隔离的 legacy adapter 中读取，不能继续暴露到新请求模型。
- [ ] 增加独立 `vessel` 和 `voyage` 字段；不得复用 `service_preference`。
- [ ] 从可报价服务范围中移除尚无完整起运地提货规则的 `door-to-port` 和 `door-to-door`；保留 `port-to-port` 和已完整实现的 `port-to-door`。
- [ ] 删除正式服务对 `fcl_quote_extractor.py`、任何 parser/extractor、AI 模型配置和 `default_fcl_quote_config()` 的导入；结构化正式路由不存在解析分支，测试对 parser/extractor 和 AI 客户端设置“调用即失败”哨兵。无已发布配置直接产生明确人工原因。
- [ ] FCL `customer_message` 保存结构化摘要，不保存或伪造原始询价文本。
- [ ] 运行定向测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/services/fcl_quote_service.py apps/api/routes/fcl_quotes.py packages/quote_engine/fcl.py tests/api/test_fcl_quotes.py tests/api/test_fcl_workflow.py tests/api/test_fcl_structured_contract.py
git commit -m "refactor(fcl): accept structured quote forms only"
```

## Task 5: 修复 FCL 货物、字段和目标 ETD 校验

**Files:**

- Modify: `packages/quote_engine/fcl.py`
- Modify: `tests/quote-engine/test_fcl_quote_engine.py`
- Create: `tests/quote-engine/test_fcl_cargo_completeness.py`
- Create: `tests/quote-engine/test_fcl_conditional_fields.py`

- [ ] 先写失败测试：
  - 仅提供 `total_weight_kg/total_volume_cbm` 的完整行参与汇总；
  - 分项只有一部分完整时，不使用部分合计自动报价；
  - 声明总量与计算值冲突时清空价格并转人工；
  - 缺少 `target_etd` 转人工；
  - 未指定船东和服务偏好不算缺字段；
  - 船名和航次分别保存；
  - 危险品要求 SDS/UN；
  - 有货值要求货值币种；
  - 进口服务条件触发进口商、BN/RM、CARM 等条件校验。
  - FCL 货物行分别使用 `unit_weight`、`piece_weights`、`line_total_weight` 时遵守同一规范化契约；多种证据不一致阻断；数量大于 1 且只有行总重时因最大单件未知阻断自动报价。
- [ ] 运行并确认至少一个行为失败。

```bash
pytest -q tests/quote-engine/test_fcl_cargo_completeness.py tests/quote-engine/test_fcl_conditional_fields.py
```

- [ ] `calculate_cargo` 只有当所有需要汇总的行都能给出重量/体积时才标记 `weight_from_items`/`volume_from_items`；部分行缺失加入 `cargo_items_incomplete`。
- [ ] FCL 重量行复用 `cargo_metrics` 的三种证据校验和规范化结果，或通过有契约测试的薄适配器保持完全相同行为；不得在 FCL 内另写“行总重 ÷ 数量”的平均单重捷径。
- [ ] `target_etd` 加入自动报价硬条件，并作为费率选择的 `pricing_date`；不再回退 `date.today()` 完成自动报价。
- [ ] `required_fields` 发布配置可以增加条件，但不能把 `carrier` 或 `service_preference` 变成系统硬编码必填。
- [ ] 明确条件字段映射并返回稳定原因代码，不在前端猜测。
- [ ] 运行定向测试，预期通过。
- [ ] 提交。

```bash
git add packages/quote_engine/fcl.py tests/quote-engine/test_fcl_quote_engine.py tests/quote-engine/test_fcl_cargo_completeness.py tests/quote-engine/test_fcl_conditional_fields.py
git commit -m "fix(fcl): validate complete cargo and ETD conditions"
```

## Task 6: 修复金额精度、每票费用和固定加价作用域

**Files:**

- Modify: `packages/quote_engine/fcl.py`
- Modify: `apps/api/db/repositories/fcl_rate_card_repository.py`
- Modify: `tests/quote-engine/test_fcl_quote_engine.py`
- Create: `tests/quote-engine/test_fcl_fee_scopes.py`
- Modify: `tests/db/test_quote_rule_config_repository.py`

- [ ] 先写失败测试：
  - `0.005/kg × 1000kg = 5.00`；
  - `1×20GP + 1×40HQ` 的同一 `per_shipment fee_id` 只收一次；
  - `per_container` 按对应柜量收取；
  - `markup_fixed` 只在整票应用一次；
  - `markup_fixed > 0` 但无 `settlement_currency` 时配置校验失败；
  - 同一票两个每票费用使用不同 `fee_id` 时分别收取。
- [ ] 运行并确认当前 `_resolve_unit_price` 提前舍入或重复加价导致失败。

```bash
pytest -q tests/quote-engine/test_fcl_fee_scopes.py tests/quote-engine/test_fcl_quote_engine.py
```

- [ ] 给 `FCLFeeLine` 增加稳定 `fee_id` 和明确 `scope`，允许值为 `per_container/per_shipment/per_piece/per_kg/per_cbm`；旧 `unit` 通过迁移 adapter 映射，发布时只保存新语义。
- [ ] 单价先应用百分比加价但不量化；`amount = money(adjusted_unit_price * quantity)`。
- [ ] 使用 `applied_shipment_fee_ids: set[str]` 跨所有柜型费率卡去重每票费用。
- [ ] `markup_fixed` 在全部费用行之后，以 `settlement_currency` 创建一条稳定 ID `quote-fixed-markup` 的报价级费用并仅加入一次。
- [ ] 内部单价保留精度；公开单价仅用于显示，不反向驱动合计。
- [ ] 仓储发布校验拒绝缺少 `fee_id`、非法 scope、重复 `fee_id` 冲突和无币种固定加价。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add packages/quote_engine/fcl.py apps/api/db/repositories/fcl_rate_card_repository.py tests/quote-engine/test_fcl_quote_engine.py tests/quote-engine/test_fcl_fee_scopes.py tests/db/test_quote_rule_config_repository.py
git commit -m "fix(fcl): enforce decimal fee and markup scopes"
```

## Task 7: 修复费率、汇率、适用范围和有效期

**Files:**

- Modify: `packages/quote_engine/fcl.py`
- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0024_fcl_rate_contracts.py`
- Modify: `apps/api/db/repositories/fcl_rate_card_repository.py`
- Modify: `tests/quote-engine/test_fcl_quote_engine.py`
- Create: `tests/quote-engine/test_fcl_rate_selection.py`
- Create: `tests/quote-engine/test_fcl_validity.py`
- Create: `tests/migrations/test_0024_fcl_rate_contracts.py`

- [ ] 先写失败测试：
  - 完整适用范围完全相同的重叠费率必须阻断，即使优先级不同；
  - 只有候选费率的合法适用范围确实不同（例如船东、服务或其他发布范围不同），并且业务选择规则允许同时成为候选时，才可用唯一最高优先级消歧；
  - 合法不同范围候选仍有并列最高优先级时阻断；
  - 指定船东后只匹配该船东；
  - 目标 ETD 超出费率有效期阻断；
  - 同币种对重叠汇率阻断；
  - 报价有效期取默认、命中费率、命中汇率中最早日期；
  - 特殊货物只能匹配包含其属性的费率卡；
  - 普通费率卡不静默用于危险品或冷藏货。
- [ ] 运行并确认当前数组顺序选择汇率、有效期只用默认天数等行为失败。

```bash
pytest -q tests/quote-engine/test_fcl_rate_selection.py tests/quote-engine/test_fcl_validity.py tests/migrations/test_0024_fcl_rate_contracts.py
```

- [ ] 给 `FCLRateCard` 和 `FCLRateCardPayload` 增加 `applicable_special_attributes`、`excluded_special_attributes`、`retired_at`、`superseded_by_id`。
- [ ] 在新建的 `0024_fcl_rate_contracts.py` 中增加本任务所需字段和约束，固定 `revision = "0024_fcl_rate_contracts"`、`down_revision = "0023_customers"`；禁止修改计划 1 已提交的 `0023_customers.py`。迁移测试覆盖升级结构和无损降级到 `0023_customers`。
- [ ] `_select_rate_card` 先过滤目标 ETD、路线、柜型、服务范围、船东/服务偏好、特殊货物，再检查重叠；定义包含路线、柜型、日期、服务范围、船东、服务、特殊属性及其他发布维度的完整 applicability key。有效期重叠且完整 key 相同就是配置冲突，优先级不同也必须阻断，不能按数据库顺序或优先级掩盖重复配置。
- [ ] 优先级只用于合法不同 applicability key 的候选消歧，并且必须得到唯一最高候选；船东/服务/范围等维度没有明确包含关系或选择规则时仍然 fail closed。
- [ ] `_find_exchange_rate` 返回 0 条、1 条或冲突结果；多于 1 条时产生 `ambiguous_exchange_rate`。
- [ ] `quote_valid_until = min(default_valid_until, *rate_effective_to, *exchange_effective_to)`；任一必要期限为空时使用其他已知最早期限，不擅自延长。
- [ ] 公开快照不返回费率 `source`、`priority`、内部 ID 或完整汇率来源。
- [ ] 运行定向测试和迁移测试，预期通过；运行 `alembic heads` 并精确断言唯一 head 为 `0024_fcl_rate_contracts`。
- [ ] 提交。

```bash
git add packages/quote_engine/fcl.py apps/api/db/models.py migrations/versions/0024_fcl_rate_contracts.py apps/api/db/repositories/fcl_rate_card_repository.py tests/quote-engine/test_fcl_quote_engine.py tests/quote-engine/test_fcl_rate_selection.py tests/quote-engine/test_fcl_validity.py tests/migrations/test_0024_fcl_rate_contracts.py
git commit -m "fix(fcl): fail closed on rate and FX ambiguity"
```

## Task 8: 重建 FCL 四步结构化销售表单

**Files:**

- Replace: `apps/web/src/components/FclQuotePanel.tsx`
- Modify: `apps/web/src/components/fclFieldLabels.ts`
- Create: `apps/web/src/features/fcl/FclQuoteForm.tsx`
- Create: `apps/web/src/features/fcl/FclRouteStep.tsx`
- Create: `apps/web/src/features/fcl/FclCargoStep.tsx`
- Create: `apps/web/src/features/fcl/FclCustomsStep.tsx`
- Create: `apps/web/src/features/fcl/FclConfirmStep.tsx`
- Create: `apps/web/src/features/fcl/fclFormState.ts`
- Create: `apps/web/src/features/fcl/FclQuoteForm.test.tsx`
- Create: `apps/web/src/features/fcl/fclFormState.test.ts`
- Modify: `apps/web/src/api/salesQuotes.ts`
- Modify: `apps/web/src/domain/quotes.ts`

- [ ] 先写测试，断言页面不出现“粘贴、解析、AI、OCR、置信度、原始询价”，且请求体没有相应字段。
- [ ] 写四步导航、必填客户名称选择、条件必填、目标 ETD、不确定 ETD 转人工提示、可选船东/服务、独立船名/航次和确认摘要测试；未选择 `customer_id` 时最终提交按钮不可用。
- [ ] 写失效测试：任何定价字段变化后清除旧预检、旧报价版本和可发送文档。
- [ ] 运行并确认现有巨型 `FclQuotePanel` 行为失败。

```bash
cd apps/web
npm test -- --run src/features/fcl/FclQuoteForm.test.tsx src/features/fcl/fclFormState.test.ts
```

- [ ] 将状态按四步切片；每步“下一步”只做本地字段校验，最终提交一次结构化 DTO。
- [ ] 客户字段复用计划 1 的 `CustomerNameField` 并提交必填 `customer_id`，不出现联系方式字段；本阶段不复制可变客户名称，计划 3 锁定报价版本时统一冻结名称快照。
- [ ] 不呈现 `service_stages` 和未实现的 `merged`；不呈现不可靠的 `door-to-port/door-to-door`。
- [ ] 自动报价结果只显示服务端 `quote_result`；前端不重算费用和有效期。
- [ ] 桌面 2–3 列，移动端单列；底部动作栏只显示“上一步/下一步/提交”。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/components/FclQuotePanel.tsx apps/web/src/components/fclFieldLabels.ts apps/web/src/features/fcl apps/web/src/api/salesQuotes.ts apps/web/src/domain/quotes.ts
git commit -m "feat(web): rebuild FCL as a structured four-step form"
```

## Task 9: 引擎阶段回归

- [ ] 运行货物和 FCL 定向测试。

```bash
pytest -q tests/quote-engine/test_cargo_metrics.py tests/ai-assistant/test_quote_extractor.py tests/api/test_ai_cargo_calculation.py tests/quote-engine/test_fcl_quote_engine.py tests/quote-engine/test_fcl_cargo_completeness.py tests/quote-engine/test_fcl_conditional_fields.py tests/quote-engine/test_fcl_fee_scopes.py tests/quote-engine/test_fcl_rate_selection.py tests/quote-engine/test_fcl_validity.py tests/migrations/test_0024_fcl_rate_contracts.py tests/api/test_fcl_structured_contract.py tests/api/test_fcl_quotes.py tests/api/test_fcl_workflow.py
```

- [ ] 运行完整报价引擎和 API 回归。

```bash
pytest -q tests/quote-engine tests/api/test_ai_auto_quote.py tests/api/test_zone_quotes.py tests/api/test_quotes_calculate.py
```

- [ ] 运行前端测试和构建。

```bash
cd apps/web
npm test -- --run
npm run build
```

- [ ] 在一次性 PostgreSQL 数据库执行线性迁移往返门禁；不得用 SQLite 替代，并确认计划 1 的 `0023_customers.py` 未被本计划修改：

```bash
alembic upgrade 0024_fcl_rate_contracts
alembic downgrade 0023_customers
alembic upgrade 0024_fcl_rate_contracts
test "$(alembic heads | awk '{print $1}')" = "0024_fcl_rate_contracts"
git diff --exit-code HEAD -- migrations/versions/0023_customers.py
```

- [ ] 搜索 FCL 新路径中的禁用字段，预期新 FCL 表单、服务和正式请求模型命中为 0。

```bash
cd ../..
rg -n "raw_message|extract_fcl_draft|fcl_quote_extractor|parse_fcl|auto_submit_when_complete|extraction_notes|confidence" apps/web/src/features/fcl apps/api/services/fcl_quote_service.py apps/api/routes/fcl_quotes.py
```

- [ ] `git diff --check`。
- [ ] 手工验证截图示例计算值和 FCL 结构化提交。
- [ ] 继续执行计划 3；不合并、不部署。
