# Canada Logistics Marketplace 架构设计

> 状态：Architecture Baseline v1.0
> 日期：2026-07-17
> 范围：MVP 目标架构、数据模型、API 合约、DDL、交付计划
> 明确不包含：业务实现、Prisma migration、NestJS/Next.js 功能代码

## 交付物索引

| PRD 输出 | 架构产物 | 说明 |
| --- | --- | --- |
| 1. 目录结构 | [01-directory-and-ddd.md](01-directory-and-ddd.md) | 目标 monorepo、DDD 模块模板、现有系统迁移位置 |
| 2. 数据库 ER 图 | [02-data-model-and-er.md](02-data-model-and-er.md) | 分域 ER 图、实体目录、约束、状态机 |
| 3. 所有模块关系图 | [03-module-context-map.md](03-module-context-map.md) | 限界上下文、同步调用、领域事件、模块依赖规则 |
| 4. API 设计 | [04-api-design.md](04-api-design.md) | REST 规范、端点清单、错误模型、幂等和 Webhook |
| 5. 数据库 DDL | [marketplace_v1.sql](../../database/marketplace_v1.sql) | PostgreSQL 基线 DDL；供下一阶段转 Prisma schema/migration |
| 6. 技术架构图 | [05-technical-architecture.md](05-technical-architecture.md) | 运行时、部署、消息、AI、安全、可观测性架构 |
| 7. MVP 开发计划 | [06-mvp-delivery-plan.md](06-mvp-delivery-plan.md) | Phase 0-10、里程碑、验收门槛、风险与迁移策略 |
| 架构决策 | [07-architecture-decisions.md](07-architecture-decisions.md) | 关键 ADR、已决事项、进入数据库开发前的评审门 |

## 一句话架构结论

MVP 使用 **Next.js Web + NestJS 模块化单体 API + NestJS Worker + PostgreSQL + Redis + RabbitMQ + S3 Compatible Storage**。领域按 DDD 限界上下文隔离，模块之间通过应用服务和领域事件协作；不允许跨模块直接访问彼此的 Repository。

## 核心设计原则

1. **交易服务能力，不固化线路产品**：服务目录、供应商能力、覆盖范围、物流计划和任务均为可组合数据。
2. **API First**：Web、供应商门户和外部集成都使用同一套 `/api/v1` 合约。
3. **模块化单体优先**：MVP 保留清晰拆分边界，但不提前承担分布式事务和微服务运维成本。
4. **确定性价格护栏**：AI 可规划、解析、预测和推荐；不得凭空生成供应商成本或绕过价格底线、毛利底线和人工审批。
5. **可追溯**：供应商原始回复、解析运行、报价版本、定价决策、履约事件和审计记录均不可覆盖式更新。
6. **可靠异步**：数据库事务内写 Outbox；Relay 投递 RabbitMQ；消费者用 Inbox 去重。
7. **最小权限**：JWT + 组织级 RBAC；供应商只能访问分配给本组织的 RFQ、报价和履约任务。
8. **PostgreSQL 是事实源**：Redis 不保存不可恢复的业务状态；S3 保存原始文件和大对象，数据库保存引用、摘要和校验和。

## MVP 边界

### 本期纳入

- 用户、组织、组织级 RBAC、会话与 API Client。
- 可后台维护的服务市场和供应商服务能力。
- Shipment Request、AI 物流方案、确定性方案校验和人工批准。
- RFQ 自动选商、Email/API/Excel/Webhook 分发、供应商回复接入。
- AI 报价解析、人工复核、标准化供应商报价。
- 最低价、最快、推荐、DDP、Self Import 多方案报价。
- 拼货池、价格锁、订单、Shipment、履约任务和统一 Tracking Timeline。
- 供应商 KPI 画像。
- Price Collector、Forecast、Recommendation、Dynamic Pricing 的数据闭环与护栏。
- 审计、通知、文件、集成连接、Outbox/Inbox 和 Dashboard 读模型。

### 本期不纳入

- 将每个领域拆成独立微服务或独立数据库。
- 自动付款、结算、发票和总账。
- 无人工审批的高风险动态价格发布。
- 自研地图、邮件、对象存储或消息中间件。
- 完整运输管理系统、车队管理、海关申报系统或仓库 WMS。
- GraphQL 业务实现；只保留 DTO/应用服务边界，便于后续增加 Adapter。

## 架构评审门

进入数据库开发前需确认以下基线：

- 模块边界和表归属是否接受。
- 组织级多租户模型是否接受。
- 金额统一使用原币 + CAD 归一化快照是否接受。
- 报价、计划和供应商回复采用不可变 revision 是否接受。
- AI 只产生候选结果、解析结果、预测和建议；确定性校验/审批负责放行是否接受。
- 当前 Python/Vite 报价系统按绞杀者模式迁移，不在本轮覆盖或删除是否接受。

## 术语

| 术语 | 定义 |
| --- | --- |
| Shipment Request | 客户提交的货物、起讫地、时间和所需服务需求 |
| Logistics Plan | 由规则和 AI 生成、经确定性校验的服务 DAG/流程 |
| RFQ | 针对一个已批准计划向供应商发起的一轮询价 |
| Supplier Quote | 供应商原始回复经标准化后的不可变报价版本 |
| Customer Quote | 平台向客户发布的报价版本，包含一个或多个可比较方案 |
| Quote Option | 最低价、最快、推荐、DDP、Self Import 等单个可接受方案 |
| Consolidation Pool | 按目的地、时间窗和服务能力聚合待拼订单的池 |
| Fulfillment Task | 从已接受方案/计划腿拆出的供应商可见履约任务 |
| Price Observation | 有来源、时间、口径和权限标签的报价/成交/价卡价格事实 |
| Pricing Decision | 动态定价策略对某次销售报价作出的、可审计且受护栏限制的决策 |
