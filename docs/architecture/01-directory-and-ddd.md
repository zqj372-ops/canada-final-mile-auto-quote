# 目录结构与 DDD 模块规范

## 1. 目标仓库结构

以下是目标态目录，不代表本轮会移动现有文件。当前 `apps/api` FastAPI 与 `apps/web` Vite 代码在迁移阶段先保留，待 NestJS/Next.js 骨架和回归测试就绪后再按迁移计划归档。

```text
canada-logistics-marketplace/
├── apps/
│   ├── web/                         # Next.js App Router；客户/销售/供应商/管理端
│   │   ├── src/app/
│   │   │   ├── (auth)/
│   │   │   ├── (customer)/
│   │   │   ├── (sales)/
│   │   │   ├── (supplier)/
│   │   │   └── (admin)/
│   │   ├── src/features/            # 按领域组织页面级功能
│   │   ├── src/components/
│   │   ├── src/lib/
│   │   └── tests/
│   ├── api/                         # NestJS HTTP API；模块化单体
│   │   ├── src/main.ts
│   │   ├── src/app.module.ts
│   │   ├── src/common/              # 仅技术横切层，不承载业务规则
│   │   └── src/modules/             # DDD 限界上下文，见第 2 节
│   ├── worker/                      # NestJS standalone；RabbitMQ consumer/scheduler
│   │   ├── src/consumers/
│   │   ├── src/jobs/
│   │   ├── src/relays/              # Outbox relay、Webhook dispatcher
│   │   └── tests/
│   └── legacy-quote-v1/             # 迁移期保留的现有 FastAPI/Vite 能力；非本轮移动
├── packages/
│   ├── contracts/                   # OpenAPI 生成类型、事件 schema、共享错误码
│   ├── database/                    # Prisma schema、migrations、seed、DB test utilities
│   │   ├── prisma/schema.prisma
│   │   ├── prisma/migrations/
│   │   └── src/client.ts
│   ├── config/                      # 环境变量 schema 和配置装配
│   ├── observability/               # logger、metrics、tracing
│   ├── security/                    # token/crypto/permission primitives
│   ├── ui/                          # 共享 UI，不放领域状态
│   └── testing/                     # factories、fixtures、contract harness
├── docs/
│   ├── architecture/                # 本架构基线
│   ├── api/                         # 生成的 OpenAPI 与集成指南
│   ├── domains/                     # 每个领域的业务词汇、状态机和约束
│   └── runbooks/                    # 运维、回滚、DLQ、数据修复手册
├── database/
│   └── marketplace_v1.sql           # 架构阶段 PostgreSQL 基线 DDL
├── infra/
│   ├── docker/
│   ├── kubernetes/                  # 规模需要时启用；MVP 可用 Compose/单集群
│   ├── terraform/
│   └── monitoring/
├── scripts/                         # 无业务逻辑的工程/迁移/校验脚本
├── tests/
│   ├── e2e/
│   ├── contracts/
│   ├── architecture/                # 模块依赖规则、越权访问、schema 漂移
│   └── performance/
├── package.json
├── pnpm-workspace.yaml
├── turbo.json
└── tsconfig.base.json
```

## 2. API 领域模块

```text
apps/api/src/modules/<module>/
├── domain/
│   ├── entities/                    # Aggregate/Entity；不依赖 Nest/Prisma
│   ├── value-objects/
│   ├── events/
│   ├── policies/                    # 纯领域规则
│   └── repositories/                # Repository interface/port
├── application/
│   ├── commands/
│   ├── queries/
│   ├── services/                    # 用例编排/事务边界
│   ├── dto/
│   └── ports/                       # Email、S3、AI、Maps 等外部 port
├── infrastructure/
│   ├── persistence/prisma/          # Repository implementation + mapper
│   ├── messaging/                   # event publisher/consumer adapter
│   └── integrations/                # 外部 port adapter
├── interface/
│   ├── http/controllers/
│   ├── http/validation/             # class-validator/Zod boundary validation
│   ├── http/presenters/
│   └── events/consumers/
├── tests/
│   ├── unit/
│   ├── integration/
│   └── contract/
├── README.md                        # 模块词汇、API、事件、表归属、SLO
└── <module>.module.ts
```

该模板完整覆盖 PRD 要求：

| PRD 要求 | DDD 落点 |
| --- | --- |
| controller | `interface/http/controllers` |
| service | `application/services`；纯业务规则放 `domain/policies` |
| repository | `domain/repositories` 接口 + `infrastructure/persistence` 实现 |
| entity | `domain/entities` |
| dto | `application/dto` |
| validation | HTTP boundary + domain invariant 两层校验 |
| test | unit/integration/contract/e2e 四层 |
| 文档 | 模块 `README.md` + `docs/domains/<module>.md` |

## 3. 限界上下文与代码模块

| 模块 | NestJS 目录 | 核心职责 | 数据所有权 |
| --- | --- | --- | --- |
| Identity & Access | `identity-access` | 用户、组织、Membership、JWT、RBAC、API Client | `users` 至 `api_clients` |
| Service Catalog | `service-catalog` | 服务分类、定义、依赖/排斥、供应商 Offering、Coverage、Facility | `service_*`, `supplier_service_*`, `facilities` |
| Shipment Request | `shipment-request` | 地址、货物、客户需求和请求状态 | `locations`, `shipment_requests`, `shipment_cargo_items`, `shipment_request_services` |
| Planning | `planning` | AI/规则生成计划、确定性校验、版本和批准 | `logistics_plans`, `plan_legs`, `plan_leg_dependencies` |
| RFQ | `rfq` | RFQ 轮次、选商、邀请、渠道发送和响应截止 | `rfqs`, `rfq_items`, `rfq_invitations`, `rfq_dispatch_attempts` |
| Supplier Quote | `supplier-quote` | 原始回复、AI 解析、标准化报价、复核 | `supplier_quotes`, `supplier_quote_items`, `supplier_quote_charges`, `quote_parse_runs` |
| Quote Center | `quote-center` | 组合供应商成本、生成/比较/发布客户方案 | `customer_quotes`, `quote_options`, `quote_option_*`, `customer_quote_acceptances` |
| Matching | `matching` | 待拼货池、候选、容量、锁价、拼仓确认 | `consolidation_pools`, `pool_memberships`, `price_locks` |
| Order | `order` | 商业订单、Shipment 编组、接受方案快照 | `orders`, `shipments`, `shipment_orders` |
| Fulfillment | `fulfillment` | 计划拆任务、供应商分配、依赖和状态历史 | `fulfillment_tasks`, `fulfillment_task_dependencies`, `fulfillment_task_status_history` |
| Tracking | `tracking` | 统一里程碑、外部事件去重和 Timeline | `tracking_milestones`, `tracking_events` |
| Supplier Center | `supplier-center` | 供应商档案、联系人、资质、投诉和 KPI 快照 | `supplier_profiles`, `supplier_contacts`, `supplier_certifications`, `supplier_complaints`, `supplier_kpi_snapshots` |
| Price Intelligence | `price-intelligence` | Price Collector/Forecast/Recommendation/Dynamic Pricing | `price_observations`, `price_forecast_*`, `price_recommendations`, `dynamic_pricing_*`, `pricing_decisions` |
| Integration | `integration` | S3 文件/关联、连接、异步操作、Webhook、Outbox/Inbox、通知 | `file_assets`, `file_asset_links`, `integration_connections`, `async_operations`, `webhook_deliveries`, `outbox_events`, `inbox_messages`, `notifications` |
| AI Governance | `ai-governance` | 模型运行、证据、Schema 校验、人工复核 | `ai_runs`, `ai_run_evidence`, `review_tasks` |
| Audit & Reporting | `audit-reporting` | 追加式审计和跨域只读投影 | `audit_logs` + 独立 read models/materialized views |

## 4. 依赖规则

1. `domain` 不依赖 NestJS、Prisma、HTTP、RabbitMQ 或具体 AI SDK。
2. `application` 仅依赖本模块 `domain` 和显式 port；不得 import 其他模块的 Infrastructure。
3. 跨模块同步协作只能调用目标模块公开的 Application Facade。
4. 跨模块异步协作使用版本化领域事件；事件 schema 位于 `packages/contracts`。
5. Repository 只能读写本模块拥有的表。跨域查询进入 Reporting projection，或调用目标模块 query facade。
6. Controller 不包含业务判断；只做认证、授权、DTO 验证、幂等上下文和用例调用。
7. Worker 复用 API 模块的 Application/Domain，不复制业务规则。
8. `common` 只放技术基元；任何包含 `Shipment`、`Quote`、`Supplier` 等业务词汇的内容必须回到所属模块。

## 5. 事务边界

| 用例 | 单事务内完成 | 事务后异步完成 |
| --- | --- | --- |
| 提交 Shipment Request | 请求状态、审计、Outbox | AI 方案生成 |
| 批准 Logistics Plan | plan revision/状态、Outbox | RFQ 草稿创建/选商建议 |
| 发布 RFQ | RFQ 状态、Invitation、Outbox | Email/API/Webhook/Excel 分发 |
| 接收供应商回复 | 原始文件/消息引用、Inbox、Outbox | AI 解析、校验、人工复核 |
| 发布 Customer Quote | 不可变报价 revision、选项、审计 | 通知客户、预热价格锁 |
| 接受 Quote Option | acceptance + order + Outbox | 入拼货池、履约准备 |
| 确认拼仓 | pool allocation、shipment 编组、Outbox | 任务拆分、通知供应商 |
| 更新履约任务 | task 状态/version、历史、Outbox | Timeline、KPI、通知 |
| 记录价格事实 | observation + lineage、Outbox | 聚合、预测训练、漂移监控 |

## 6. 目标态 Web 结构

```text
apps/web/src/features/
├── auth/
├── service-marketplace/
├── shipment-requests/
├── logistics-planner/
├── rfq-center/
├── supplier-quotes/
├── quote-comparison/
├── consolidation-pools/
├── orders/
├── fulfillment/
├── tracking/
├── supplier-center/
├── price-intelligence/
└── admin/
```

页面按角色组合 feature，不复制领域逻辑：

- 客户：服务勾选、需求提交、方案/报价比较、订单、Tracking。
- 销售：客户需求、推荐报价、价格护栏、成交、异常处理。
- 供应商：RFQ 收件箱、报价提交、本人任务、状态更新、绩效。
- 管理员：服务目录、供应商、策略、权限、集成、审计和 Dashboard。

## 7. 下一阶段目录变更策略

数据库开发开始时只新增目标数据库包和迁移，不立即删除现有系统：

1. 创建 `packages/database/prisma/schema.prisma`。
2. 把本架构 DDL 翻译为 Prisma schema，并生成 `0001_marketplace_baseline` migration。
3. 用 PostgreSQL 临时库执行空库迁移、回滚演练和约束测试。
4. NestJS 骨架就绪后，再将当前 FastAPI/Vite 移到 `apps/legacy-quote-v1`。
5. 将现有 Zone Quote Engine 作为确定性算法基线，用黄金样例做 TypeScript 端口的行为一致性测试。
