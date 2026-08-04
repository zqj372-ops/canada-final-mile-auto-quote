# AI Quote Product Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 AI 报价程序中完成销售前台、运营后台、确定性报价、不可变版本、配置发布、PDF 发送和客户结果的完整业务闭环。

**Architecture:** 保留 FastAPI、SQLAlchemy、React 和现有报价引擎，以 `SalesQuoteRecord` 为聚合根；前端拆成 `/quote/*` 与 `/admin/*` 两个独立应用壳；每次正式提交都生成不可变 `QuoteVersion`，失败/人工尝试版本明确不可发送，PDF、发送和客户结果只绑定当前锁定可发送版本。

**Tech Stack:** Python 3.11、FastAPI、Pydantic 2、SQLAlchemy 2、Alembic、PostgreSQL、Pytest、React 18、TypeScript、Vite、Vitest、Testing Library、Playwright Chromium（服务端 PDF 渲染与端到端验收）。

---

## 1. 计划入口

业务和交互源规格：

- `docs/superpowers/specs/2026-08-03-ai-quote-product-redesign-design.md`

按以下顺序执行五份计划：

1. `docs/superpowers/plans/2026-08-03-ai-quote-foundation-and-shells.md`
2. `docs/superpowers/plans/2026-08-03-quote-inputs-and-deterministic-engines.md`
3. `docs/superpowers/plans/2026-08-03-quote-review-versions-and-records.md`
4. `docs/superpowers/plans/2026-08-03-pricing-config-and-management-data.md`
5. `docs/superpowers/plans/2026-08-03-pdf-send-and-customer-outcomes.md`

计划 1 是所有工作的共同前置。计划 2 完成后才能把自动报价结果锁定为版本。迁移链和业务契约存在严格依赖，因此 Luna 按计划 1 → 2 → 3 → 4 → 5 线性执行；可以并行做只读审查，但不得并行创建、改写或应用迁移。最终回归必须覆盖全部五个计划。

## 2. 分支和基线

- [ ] 不在 `main` 上开发，也不合并 Draft PR #3。
- [ ] 从 `origin/codex/fcl-quote-workflow-rework` 创建实施分支；该分支已包含 `codex/fcl-quote-form-alignment` 和提交 `7baa129`。
- [ ] 运行 `git merge-base --is-ancestor 7ec30ea HEAD`，预期退出码为 0。
- [ ] 运行 `git merge-base --is-ancestor 7baa129 HEAD`，预期退出码为 0。
- [ ] 运行 `alembic heads`，开始实施前预期只有 `0022_quote_workflow (head)`。
- [ ] 运行 `git status --short`，确认没有覆盖其他工作树的未提交修改。

推荐命令：

```bash
git fetch origin
git switch -c codex/ai-quote-product-redesign origin/codex/fcl-quote-workflow-rework
git merge-base --is-ancestor 7ec30ea HEAD
git merge-base --is-ancestor 7baa129 HEAD
alembic heads
git status --short
```

如果 Luna 已在 `codex/fcl-quote-workflow-rework` 工作树中，直接从当前干净提交创建 `codex/ai-quote-product-redesign`，不要重复 cherry-pick `7baa129`，也不要创建第二个 `0022`。

## 3. 迁移编号和数据库规则

- [ ] 现有工作流迁移固定为 `0022_quote_workflow`；开始前确认 `down_revision="0021_fcl_quote_closed_loop"`，禁止再创建第二个 `0022`。
- [ ] 每个迁移只由一个任务创建并在首次应用后冻结，严格使用以下单链：
  - `0023_customers` → `down_revision="0022_quote_workflow"`
  - `0024_fcl_rate_contracts` → `down_revision="0023_customers"`
  - `0025_quote_versions` → `down_revision="0024_fcl_rate_contracts"`
  - `0026_fcl_pricing_releases` → `down_revision="0025_quote_versions"`
  - `0027_pricing_maintenance_tasks` → `down_revision="0026_fcl_pricing_releases"`
  - `0028_quote_documents` → `down_revision="0027_pricing_maintenance_tasks"`
  - `0029_quote_delivery` → `down_revision="0028_quote_documents"`
- [ ] 禁止后续任务向已经在任何开发库执行过的迁移文件追加操作；模型变化必须创建链上的下一个迁移。
- [ ] 所有 JSON 字段为非空时给出明确默认值；禁止用 Python 可变对象作为 SQLAlchemy 共享默认值。
- [ ] 真实 PostgreSQL 升级是上线门槛；SQLite 只能用于快速单元测试，不能替代 PostgreSQL 迁移验证。
- [ ] 旧记录先审计再回填：只有存在发送、结果或任务证据时才映射相应状态；无法可靠判断的记录进入 `legacy_unclassified` 和迁移异常清单，不得被默认伪造成 `pending_review`、`sent` 或已结束。

## 4. 统一工程规则

- [ ] 每个行为先写一个最小失败测试，运行并记录预期失败，再实现，再运行通过。
- [ ] 每个任务完成后只提交该任务相关文件；不夹带视觉概念文件、构建产物、数据库文件或本机配置。
- [ ] 服务端负责状态、权限、金额、版本、有效期和合法动作；前端只呈现服务端响应。
- [ ] 所有公开 DTO 通过递归 allowlist 生成，禁止 `dict.pop()` 式黑名单成为唯一保护。
- [ ] 所有写动作接受 `Idempotency-Key`，非法状态或 revision 冲突返回 `409`。
- [ ] 所有金额使用 `Decimal` 到行金额后再舍入；TypeScript 只格式化服务端给出的字符串金额。
- [ ] 已锁定版本、已生成文档和成功发送事件不可更新，只能追加新实体。
- [ ] 复核只提交费用行和类型化人工换汇依据；币种小计、折算总价、PDF 金额全部由服务端从当前版本重新派生。
- [ ] `customer_name` 在版本创建时冻结；客户目录改名不得改写历史页面、回复、文档或发送证据。
- [ ] 销售接口不返回供应商、成本、source、priority、rate card、内部汇率源或内部备注。
- [ ] 管理员创建报价时使用销售前台流程；后台不增加“替客户发送”动作。

## 5. 每阶段提交建议

按任务小步提交，至少形成这些检查点：

```text
test(web): add sales and admin shell test harness
feat(web): separate sales and admin application shells
feat(customers): add minimal customer directory
fix(cargo): derive authoritative cargo totals from item rows
fix(fcl): fail closed on ambiguous deterministic pricing
feat(quotes): add immutable quote versions
feat(review): create locked reviewed versions atomically
feat(web): rebuild sales records and operations review flows
feat(config): validate and atomically publish pricing versions
feat(admin): add maintenance tasks and commercial metrics
feat(pdf): render and persist version-bound quote documents
feat(delivery): record sends follow-ups and customer outcomes
test(e2e): cover automatic and reviewed quote loops
```

## 6. 跨计划验收矩阵

| 场景 | 计划 1 | 计划 2 | 计划 3 | 计划 4 | 计划 5 |
| --- | --- | --- | --- | --- | --- |
| 前后台独立入口和权限 | 主责 | 回归 | 复核页 | 配置页 | 发送页 |
| 客户仅名称 | 主责 | 表单使用 | 版本冻结名称 | 指标使用 | 收件人不回写客户 |
| 加拿大末端重新计算 | 壳层 | 主责 | 锁定版本 | 规则健康 | PDF 同源 |
| FCL 仅结构化表单 | 壳层 | 主责 | 记录展示 | 必填配置 | PDF 同源 |
| 自动 V1 / 复核 V2 | 基础模型 | 输入快照 | 主责 | 发布版本来源 | 文档绑定 |
| 配置 fail closed | 权限 | 引擎行为 | 人工入口 | 主责 | 过期阻断 |
| PDF/发送/客户结果 | 动作占位禁用 | 金额契约 | 版本基础 | 模板配置 | 主责 |

## 7. 最终验证

- [ ] `pytest -q tests`
- [ ] `pytest -q tests/quote-engine tests/services tests/api`
- [ ] `alembic heads`，预期只有 `0029_quote_delivery (head)`。
- [ ] 在一次性 PostgreSQL 数据库执行 `alembic upgrade head`。
- [ ] 对包含旧 `SalesQuoteRecord` 和 `ManualQuoteTask` 数据的快照执行升级，核对 backfill 数量和状态。
- [ ] 在一次性 PostgreSQL 库完成 `upgrade head → 数据断言 → downgrade 0022_quote_workflow → upgrade head → 数据断言`；每次只有一个 head，升级/降级均无孤儿版本、错误状态或丢失历史证据。
- [ ] 在 `apps/web` 执行 `npm test -- --run`。
- [ ] 在 `apps/web` 执行 `npm run build`。
- [ ] 在 1440×900 和 390×844 走通核心页面，确认无横向溢出，且 axe `serious/critical` 违规为 0。
- [ ] 正式销售和后台核心路由不再加载 `legacy.css`；仅允许 `/admin/tools/*` 使用显式 scoped 的兼容样式，并在 PR 风险中列明。
- [ ] 执行服务端 PDF Chromium smoke test，验证输出以 `%PDF-` 开头且数据库哈希匹配文件哈希。
- [ ] 浏览器走通五条验收路径：加拿大末端自动、FCL 自动、FCL 补资料复核、发送失败、客户要求调整。
- [ ] 用销售账号检查他人记录返回 `403`；用 viewer 检查写接口返回 `403`。
- [ ] 对销售详情、PDF HTML、PDF 文本和网络响应搜索内部字段名，结果为 0。
- [ ] `git diff --check`
- [ ] `git status --short` 只显示本计划预期文件，提交后工作树干净。

推荐最终命令：

```bash
pytest -q tests
alembic heads
cd apps/web
npm test -- --run
npm run build
cd ../..
git diff --check
git status --short
```

PostgreSQL 迁移验证示例：

```bash
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic upgrade head
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic downgrade 0022_quote_workflow
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic upgrade head
```

## 8. 交付边界

- [ ] 推送 `codex/ai-quote-product-redesign`。
- [ ] 创建或更新 Draft PR，目标为 `main`。
- [ ] PR 描述按设计规格章节列出完成、未完成、测试证据、迁移证据和残余风险。
- [ ] 保持 Draft，等待用户确认真实 PostgreSQL、浏览器验收和视觉验收结果。
- [ ] 未经用户明确授权，不合并 `main`，不部署服务器，不修改生产配置。
