# Phase 2A+B：AI 报价确认工作台设计

## 1. 文档状态

- 状态：待用户审阅
- 范围：第二阶段 A+B，仅处理提取、确认报价、销售报价工作台和既有接口兼容
- 当前已确认的页面方案：A，固定三栏工作台
- 当前已确认的接口策略：新增双接口，保留 `/quotes/ai-auto-quote` 兼容旧调用方

本设计不创建 `QuoteCase`、`QuoteRevision` 或其他数据库表，不修改 `manual_quote_tasks` 数据模型，不处理客户发送、FCL、Marketplace、价格矩阵业务数据、异常中心和完整后台导航重构。

## 2. 背景与问题边界

当前 `/quote` 的 `handleSmartQuote` 将以下动作绑定在一次点击中：

1. AI 提取客户原文；
2. 直接调用报价流程；
3. 写入销售报价记录；
4. 创建人工任务或发送通知；
5. 用结果弹窗承载报价结果。

当前后端 `/quotes/ai-auto-quote` 也将提取和报价放在同一服务中。虽然 Phase 1 已经固定了 Hermes 的价格权限边界，但页面仍然无法区分：

- AI 只是提取出了字段；
- 用户尚未确认字段；
- Quote Engine 已经成功报价；
- Quote Engine 要求人工复核；
- 请求或依赖发生了系统错误。

本阶段的核心约束是：

> AI 只产生可供人确认的结构化草稿；只有前端确认后的结构化字段才能进入 Quote Engine；价格和正式报价状态只能由 Quote Engine 及其既有审计/任务边界产生。

## 3. 设计决策

### 3.1 页面采用固定三栏工作台

桌面端固定为以下比例：

| 区域 | 目标宽度 | 内容 | 权限边界 |
| --- | ---: | --- | --- |
| 左栏 | 34% | 客户原始消息、提取动作、提取状态、原文证据 | 不显示可发送金额 |
| 中栏 | 41% | 结构化地址、货物、服务字段、字段来源和人工编辑 | 用户确认最终输入 |
| 右栏 | 25% | Quote Engine 结果、金额、来源、风险、复制/导出权限 | 只展示真实结果状态 |

结果不使用全屏弹窗。地图可作为地址验证抽屉打开；乡村 FSA 二次确认显示在右栏结果区域内，不再把报价结果本身包在模态框里。

桌面端之外按“左栏 → 中栏 → 右栏”的顺序堆叠。移动端不试图保留三栏并排，也不因此引入另一套业务流程。

### 3.2 新工作台使用两个新接口

新 `/quote` 不再调用 `/quotes/ai-auto-quote`，而是调用：

```text
POST /quotes/ai-extract
POST /quotes/confirmed-calculate
```

旧 `/quotes/ai-auto-quote` 暂时保留给当前 `/ai-quote` 页面和已有调用方。它的兼容行为不向新工作台扩散；后续如果要废弃，另行做迁移设计。

### 3.3 现有表继续作为过渡存储

本阶段不新增表：

- `sales_quote_records` 继续承载已经提交过报价动作的销售记录；
- `manual_quote_tasks` 继续承载某次报价触发的人工复核任务；
- `quote_audits` 继续承载 Quote Engine 审计；
- `hermes_diagnostic_queue` 继续承载既有诊断链路。

AI 提取完成但尚未确认报价，不是正式报价记录，也不是人工任务。它只存在于当前前端工作台状态中。

## 4. API 设计

### 4.1 `POST /quotes/ai-extract`

#### 请求

```json
{
  "customer_message": "客户原始询价",
  "ai_config_id": 12,
  "enable_search_context": false,
  "search_config_id": null
}
```

字段要求：

- `customer_message` 必填且不能为空；
- `ai_config_id`、`search_config_id` 可为空；
- `enable_search_context` 默认 `false`；
- 不接受 `auto_submit_when_complete`、通知开关、邮箱配置或企业微信配置。

#### 响应

```json
{
  "extraction": {
    "address_line": "...",
    "postal_code": "L4K 2N2",
    "city": "Concord",
    "province": "ON",
    "cbm": "4.2",
    "weight_kg": "850",
    "piece_count": 10,
    "packaging_type": "carton",
    "longest_side_cm": null,
    "explicit_pallet_count": null,
    "is_stackable": null,
    "address_type": "commercial",
    "requires_liftgate": false,
    "requires_pallet_jack": false,
    "requires_appointment": true,
    "detention_minutes": 0,
    "missing_fields": [],
    "confidence": 92,
    "extraction_notes": null,
    "cargo_items": [],
    "cargo_agent": null,
    "address_agent": null,
    "validation_notes": []
  },
  "missing_fields": [],
  "address_validation": null,
  "search_context": null
}
```

响应可以复用现有 `AIExtractedQuoteDraft`、`LocalAddressValidation` 和 `QuoteSearchContext` 类型，但不得包含以下内容：

- `quote_result`；
- `total_price_usd` 或任何可发送给客户的金额；
- `customer_reply`；
- `sales_quote_records` ID；
- `manual_review_required` 作为报价结论。

#### 副作用规则

该接口：

- 可以读取 AI 配置、本地邮编库和可选搜索上下文；
- 不调用 `ZoneQuoteEngine`；
- 不查询或应用 `learned_quote_rules`；
- 不写 `sales_quote_records`；
- 不创建 `manual_quote_tasks`；
- 不写报价审计；
- 不发送邮件、企业微信或客户通知。

权限沿用当前 AI 自动报价接口的 `AI_QUOTE_WRITE_ROLES`，不新增角色权限。

AI 模型失败时，可以沿用当前确定性解析 fallback，返回没有金额的提取结果和 `validation_notes`。只有配置不存在、请求无法处理等真正接口错误才返回 HTTP 错误；不能把系统错误伪装成 `manual_required`。

### 4.2 `POST /quotes/confirmed-calculate`

#### 请求

```json
{
  "customer_message": "客户原始询价",
  "quote": {
    "address_line": "8888 Keele St",
    "postal_code": "L4K 2N2",
    "city": "Concord",
    "province": "ON",
    "cbm": "4.2",
    "weight_kg": "850",
    "piece_count": 10,
    "packaging_type": "carton",
    "longest_side_cm": null,
    "address_type": "commercial",
    "requires_liftgate": false,
    "requires_pallet_jack": false,
    "requires_appointment": true,
    "explicit_pallet_count": null,
    "is_stackable": null,
    "detention_minutes": 0
  },
  "extraction_snapshot": null,
  "field_provenance": {
    "postal_code": "human_edited",
    "cbm": "ai_extracted",
    "weight_kg": "customer_original",
    "billing_pallets": "system_derived"
  }
}
```

说明：

- `customer_message` 只用于审计和销售记录原文保存，不重新驱动 AI 提取；
- `quote` 是唯一进入 Quote Engine 的输入；
- `extraction_snapshot` 和 `field_provenance` 只用于审计/UI 回显，不得参与金额计算；
- `field_provenance` 的值限定为 `customer_original`、`ai_extracted`、`system_derived`、`human_edited`；
- 后端不能从 `customer_message`、`extraction_snapshot` 或 `field_provenance` 再推导或覆盖 `quote`。

#### 响应

```json
{
  "quote_result": {
    "quote_id": "...",
    "source_type": "zone_matrix",
    "manual_review_required": false,
    "total_price_usd": "212.00"
  },
  "sales_record_id": 123
}
```

响应完整保留现有 `ZoneQuoteResult` 字段；`sales_record_id` 用于前端刷新或定位报价记录。

#### 计算与副作用顺序

服务层必须沿用统一 Zone Quote Engine 管道：

```text
ZoneQuoteEngine.quote(confirmed_quote)
→ apply_learned_quote_if_available()
→ enforce_origin_matrix_safety()
→ enforce_zone_price_switch()
→ attach_zone_quote_logic()
→ 写 quote audit / diagnostic
→ manual_review_required 时创建 manual_quote_task
→ 创建 sales_quote_record
```

Phase 1 的权限边界继续有效：只有原始 Quote Engine 结果为 `manual_review_required=true` 时，才允许尝试 learned quote rule；成功的正式 `zone_matrix` 结果不能被学习规则覆盖。

本接口不接受通知参数，也不触发默认成功邮件、企业微信或人工复核通知。人工任务仍然创建，但通知由后续异常中心/通知动作显式触发。

权限沿用当前 `/quotes/zone-calculate` 的 `QUOTE_WRITE_ROLES`。这是已有的直接报价权限，不是因为新接口而扩大人工报价权限。

#### 记录状态

| 最终结果 | `sales_quote_records.status` | 是否创建人工任务 | 是否创建销售记录 |
| --- | --- | --- | --- |
| `manual_review_required=false` 且有金额 | `quoted` | 否 | 是 |
| `manual_review_required=true` | `manual_required` | 是 | 是 |
| 系统异常、没有 `ZoneQuoteResult` | 不写 | 否 | 否 |

系统异常不允许落成 `manual_required`，因为那会把依赖故障与业务复核混为一谈。

### 4.3 旧接口兼容规则

`POST /quotes/ai-auto-quote` 在本阶段继续保留原响应形状和既有通知参数，供旧 `/ai-quote` 页面及已有调用方使用。新 `/quote` 不调用它。

必须修正一项旧语义：当 `auto_submit_when_complete=false` 且没有 `quote_result`、也没有业务人工复核时，不得写入 `sales_quote_records.status="quoted"`。在现有无迁移约束下，最诚实的兼容行为是跳过正式销售记录写入；该响应只是提取草稿，直到调用新 `confirmed-calculate`。

## 5. 前端状态机

前端使用明确的状态枚举，不再用视觉上的三个标签代替真实业务状态：

```text
EMPTY → EXTRACTING
           ├─ missing_fields → NEEDS_INPUT
           ├─ complete        → READY_TO_QUOTE → QUOTING
           │                                      ├─ quoted  → QUOTED
           │                                      └─ review  → REVIEW_REQUIRED
           └─ request error   → SYSTEM_ERROR

QUOTED / REVIEW_REQUIRED ──编辑报价字段──→ STALE
STALE ──重新报价成功──→ QUOTED 或 REVIEW_REQUIRED
```

### 5.1 状态定义

| 状态 | 含义 | 右栏 | 允许动作 |
| --- | --- | --- | --- |
| `EMPTY` | 没有客户原文或尚未开始 | 空状态 | 粘贴原文 |
| `EXTRACTING` | 正在调用 AI 提取 | 显示处理中 | 取消/等待 |
| `NEEDS_INPUT` | 缺少必需字段或地址仍需确认 | 不显示金额 | 编辑字段、重新提取 |
| `READY_TO_QUOTE` | 必需字段已齐，等待人工确认后报价 | 显示待报价 | 确认并计算报价 |
| `QUOTING` | 正在调用 Quote Engine | 显示计算中 | 禁止重复提交 |
| `QUOTED` | 正式报价成功且当前输入未变化 | 显示金额和来源 | 复制、导出、查看风险 |
| `REVIEW_REQUIRED` | Quote Engine 最终要求人工复核 | 不允许发送确定金额 | 查看原因、进入后续任务动作 |
| `STALE` | 报价后关键字段发生变化 | 保留旧金额供对比，但禁用复制/导出/发送 | 重新报价 |
| `SYSTEM_ERROR` | 网络、配置、依赖或服务异常 | 不显示可发送金额 | 重试、查看技术错误 |

`SYSTEM_ERROR` 是前端操作状态，不新增后端报价状态枚举，也不写入 `sales_quote_records` 或 `manual_quote_tasks`。

### 5.2 关键转移规则

- `EXTRACTING` 成功但有 `missing_fields` → `NEEDS_INPUT`；不创建人工任务；
- `EXTRACTING` 成功且字段齐全 → `READY_TO_QUOTE`；仍不自动调用 Quote Engine；
- 用户编辑任何进入 `ZoneQuoteRequest` 的字段：
  - `QUOTED` 或 `REVIEW_REQUIRED` → `STALE`；
  - 清空/修改字段时保留上一份 `quote_result` 和报价输入快照用于对比；
- 只有点击“确认字段并计算报价”才进入 `QUOTING`；
- `QUOTING` 返回最终 `manual_review_required=false` 且金额存在 → `QUOTED`；
- `QUOTING` 返回 `manual_review_required=true` → `REVIEW_REQUIRED`；
- HTTP/网络/解析错误 → `SYSTEM_ERROR`，不得转成 `REVIEW_REQUIRED`；
- `STALE` 只有重新成功调用 `confirmed-calculate` 后才能回到 `QUOTED` 或 `REVIEW_REQUIRED`。

### 5.3 字段来源

中栏每个可报价字段显示来源标签：

- `客户原文`：从 customer_message 中可直接确认；
- `AI 提取`：AI 或确定性 fallback 产生；
- `系统推导`：例如计费托数、Zone、燃油和附加费；
- `人工修改`：报价员在确认前修改。

字段来源不授予价格权限。`system_derived` 只描述字段来源；价格仍由 Quote Engine 产生。

## 6. 工作台交互设计

### 6.1 左栏：原始询价

- 保留完整 customer message，不截断作为唯一证据；
- 主按钮为“解析字段”，不再叫“AI 自动报价”；
- 展示 AI 配置和可选搜索上下文，但不展示通知开关；
- 提取阶段显示 `EXTRACTING`；提取完成后显示缺失字段和解析备注；
- 不在左栏生成客户可发送金额。

### 6.2 中栏：结构化确认

- 地址、货物、包装、地址类型、尾板/手叉车/预约/等待时间均为可确认字段；
- 字段完整时显示“确认字段并计算报价”；
- 关键字段变化会触发 `STALE`；
- 地址验证结果和搜索上下文只作为证据/风险提示；
- 地图在抽屉中打开，不改变报价输入权威。

### 6.3 右栏：报价与风险

- 结果区域固定或 sticky；
- `QUOTED` 显示 total、source_type、matched_rule、Zone、计费托数、风险标签和审计入口；
- `REVIEW_REQUIRED` 显示“需人工复核”和原因，不显示可发送金额；
- `SYSTEM_ERROR` 显示错误类别和重试按钮，不生成虚假的人工任务提示；
- `STALE` 显示上一版本结果、发生变化的字段和“重新报价”；
- 复制/导出仅在 `QUOTED` 且未 stale、必要的乡村地址确认已完成时启用；
- 本阶段不接入真实客户发送动作。

## 7. 代码组织方向

实现时保持现有 React/Vite 技术栈，不建立第二套前端应用：

- `apps/web/src/pages/QuotePage.tsx` 保留路由入口，但收敛为工作台状态编排；
- 新增或整理 `apps/web/src/components/quote-workbench/` 下的三栏、状态条、字段来源、结果/风险组件；
- `apps/web/src/api/client.ts` 增加两个请求类型、响应类型和调用函数；
- 将状态转移抽成纯函数/reducer，避免把状态判断散落在 JSX 事件处理器中；
- `apps/api/services/ai_quote_service.py` 抽取无副作用的提取阶段服务，旧自动报价路径复用但保留兼容行为；
- 新增 confirmed calculate 服务/路由，复用 `quote_service.py` 的统一报价管道；
- 为 `record_zone_quote_side_effects` 增加明确的通知开关或等价的无通知调用路径，不能用隐式全局开关；
- 不修改价格矩阵数据，不新增数据库迁移。

不把所有代码继续堆回一个超大 `QuotePage.tsx`，也不在本阶段重构记录、异常中心和设置页的信息架构。

## 8. 验证与验收

### 8.1 后端 API 测试

至少覆盖：

1. `ai-extract` 完整字段返回提取结果，不调用 Quote Engine；
2. `ai-extract` 缺少字段时返回 `missing_fields`，不创建任务/记录/通知；
3. `ai-extract` 返回地址验证和可选搜索上下文时，不产生金额；
4. `confirmed-calculate` 不调用 AI 提取；
5. `confirmed-calculate` 使用确认后的结构化字段，即使原始消息内容不同也不重新推导；
6. 成功结果写入 `sales_quote_records.status="quoted"`，并保留原始 source、金额、matched_rule；
7. 最终人工复核结果创建 `manual_quote_tasks` 和 `sales_quote_records.status="manual_required"`，但不发送默认通知；
8. 系统异常不创建销售记录或人工任务，也不返回 `manual_required`；
9. Phase 1 learned rule 边界继续通过：成功的 Zone Matrix 结果不被学习规则覆盖，原始 manual result 仍可尝试复用；
10. 旧 `auto_submit_when_complete=false` 响应不再产生 `quoted` 的空报价记录。

### 8.2 前端验证

在现有无专用前端测试脚本的前提下，本阶段至少执行：

- `npm run build`；
- 浏览器验证完整链路：空状态 → 解析 → 缺字段 → 编辑确认 → 计算 → 成功；
- 浏览器验证 `REVIEW_REQUIRED` 和 `SYSTEM_ERROR` 不混淆；
- 浏览器验证报价后修改关键字段进入 `STALE`，旧金额不可复制/导出；
- 浏览器验证报价结果常驻右栏、不依赖结果弹窗；
- 浏览器验证刷新报价记录后状态与后端真实值一致。

### 8.3 完成标准

本阶段只有同时满足以下条件才能称为完成：

- 新工作台只通过双接口完成提取和确认报价；
- 未确认字段不会触发 Quote Engine；
- 没有把系统异常显示成业务人工复核；
- 没有把提取草稿写成 `quoted` 报价记录；
- 成功报价、人工复核和 stale 状态的复制/导出权限正确；
- 相关后端测试和前端 build/浏览器验收有实际输出；
- 没有新增数据库迁移或扩展到 QuoteCase 等下一阶段数据模型。

## 9. 后续阶段明确不在本设计内

以下事项留到本阶段验证完成后单独设计：

- `QuoteCase` 与 `sales_quote_records` 的 ADR；
- `QuoteRevision` 和报价版本不可变存储；
- 统一异常中心队列和动作式状态转换；
- 价格中心拆分、导入预览、版本发布和变更日志；
- 客户邮箱、发送记录和发送/接受/失效状态；
- `/ai-quote` 移入“系统设置 → AI 实验室”的完整导航重构；
- 运营角色和菜单的全面权限重整。
