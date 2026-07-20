# 架构决策记录（ADR Summary）

## ADR-001：MVP 使用模块化单体，而非微服务

- **状态**：Accepted。
- **决策**：一个 NestJS API deployment，按 DDD 模块隔离；另有独立 Worker deployment。
- **原因**：核心交易需强事务一致性，团队和流量尚无证据支持微服务成本。
- **后果**：必须用 architecture tests 和表 ownership 防止“名义模块化、实际大泥球”；未来可按事件/API 边界拆分。

## ADR-002：PostgreSQL 是唯一业务事实源

- **状态**：Accepted。
- **决策**：业务状态、幂等、Outbox/Inbox、审计均以 PostgreSQL 为准；Redis 只做可重建缓存/限流/短锁。
- **后果**：最终写入必须回 DB 校验；Redis 丢失不能造成价格、容量或状态错误。

## ADR-003：一个物理 schema，逻辑表所有权

- **状态**：Accepted for MVP。
- **决策**：使用 PostgreSQL `marketplace` schema；模块 ownership 由 Repository、代码边界、文档和测试实施。
- **原因**：减少 Prisma multi-schema、跨 schema migration 和本地/测试差异。
- **后果**：跨模块 FK 可用于重要一致性，但业务代码不得直接跨模块 Repository。

## ADR-004：组织级 RBAC，而非用户单角色字段

- **状态**：Accepted。
- **决策**：User ↔ Organization Membership ↔ Role ↔ Permission；一个用户可属于多个组织。
- **原因**：平台销售、客户和供应商的权限天然是组织上下文，单个 `user.role` 无法表达。
- **后果**：所有组织级请求需要 `X-Organization-Id` 和 resource ownership check。

## ADR-005：计划和报价使用不可变 revision

- **状态**：Accepted。
- **决策**：Logistics Plan、Supplier Quote、Customer Quote 修改产生新 revision；旧版保留。
- **原因**：RFQ、客户接受、价格锁和履约必须引用当时快照，不能被后续供应商更新悄悄改写。
- **后果**：数据量增大；换取审计、复现、争议处理和模型训练的可靠来源。

## ADR-006：Plan 使用 DAG，界面可显示线性序列

- **状态**：Accepted。
- **决策**：`plan_legs.sequence_number` 用于默认展示，`plan_leg_dependencies` 表达真实依赖。
- **原因**：仓储、报关、分拨和并行增值服务并非永远是纯链表。
- **后果**：批准前必须做无环、连通、必需服务覆盖和地点连续性校验。

## ADR-007：AI 只产生候选/建议，确定性系统放行

- **状态**：Accepted。
- **决策**：AI 可生成 Plan、解析报价、预测、推荐和解释；Schema、来源、算术、价格 floor/cap、状态转换和审批在模型外执行。
- **原因**：延续现有系统“AI 不编造价格”的核心安全边界。
- **后果**：每次模型运行保存 provider/model/prompt/schema/evidence；失败进入 Review，不伪造结果。

## ADR-008：金额保留原币并归一化 CAD

- **状态**：Accepted。
- **决策**：交易事实保留原币；Price Observation 另存 CAD 金额和当时 FX rate。
- **原因**：报价/结算争议需要原币事实，跨城市预测和利润分析需要共同口径。
- **后果**：下一阶段必须选择 FX 来源、时间点和缺失/修正规则。

## ADR-009：Outbox/Inbox + RabbitMQ 至少一次投递

- **状态**：Accepted。
- **决策**：本地事务写 Outbox，Relay 投 RabbitMQ，Consumer 用 Inbox/业务唯一键去重。
- **原因**：避免数据库成功但消息丢失，同时接受现实中的重复投递。
- **后果**：所有消费者和外部发送必须幂等；不声称 exactly-once。

## ADR-010：REST/OpenAPI First，GraphQL 暂不实现

- **状态**：Accepted。
- **决策**：MVP 使用 `/api/v1` REST；Application Query/Command 边界为未来 GraphQL Adapter 预留。
- **原因**：外部供应商集成、Webhook、SDK 和审计更适合稳定明确的 REST contract；当前无 GraphQL 必要性。
- **后果**：CI 做 OpenAPI breaking-change gate；Controller 不承载业务规则。

## ADR-011：Order 与 Shipment 分离

- **状态**：Accepted。
- **决策**：Order 表示商业承诺；Shipment 表示运营编组；通过 join 支持多订单拼货和未来拆单。
- **原因**：若一单一 Shipment 硬绑定，撮合中心无法自然表达合并/拆分。
- **后果**：Tracking 以 Shipment 为主，客户视图需要聚合其 Order 关联的 Shipment。

## ADR-012：Price Intelligence 是独立上下文

- **状态**：Accepted。
- **决策**：Collector/Forecast/Recommendation/Dynamic Pricing 独立拥有 observation/model/recommendation/policy/decision 数据。
- **原因**：它消费多个交易领域的事实，但不应反向拥有 RFQ/Quote/Order 状态。
- **后果**：只通过 advisory facade/事件影响 Quote/RFQ；不得直接写 Quote Repository。

## ADR-013：Price Intelligence 默认保护供应商价格隐私

- **状态**：Accepted。
- **决策**：单供应商 observation 默认 PRIVATE；跨供应商展示/模型特征需授权、去标识化和最小样本规则。
- **后果**：Dashboard/Recommendation 分离 internal raw 和 aggregated surface；所有访问审计。

## ADR-014：现有系统使用 Strangler 迁移

- **状态**：Accepted。
- **决策**：保留现有 FastAPI/Vite 与确定性 Zone Engine；通过 Adapter、golden fixture、dual-run 和 feature flag 逐步迁移。
- **原因**：现有规则与安全护栏是资产，直接重写/覆盖会产生不可接受的报价回归风险。
- **后果**：目标目录是 future state，本轮和数据库阶段不删除现有代码/数据。

## 进入数据库开发前需业务确认

这些问题不阻塞架构文档完成，但必须在相关 migration/seed 或自动化上线前由 Owner 确认：

| 决策 | 当前默认 | 必须确认时间 | Owner |
| --- | --- | --- | --- |
| 平台是否一个客户/供应商一个 Organization | 是；允许 BOTH | Phase 1 | Product |
| 系统角色/权限初始矩阵 | 文档中的四角色 + 细粒度 permission | Phase 1 | Product/Security |
| FX 数据源与锁定时间 | 每个 observation/quote 保存来源和快照 | Phase 5 | Finance/Product |
| 税、GST、CARM、DDP 的业务责任边界 | 作为可组合服务，不自动承担法律/税务判断 | Phase 3 | Customs/Finance |
| Supplier KPI 公式/权重 | 原始指标分开存，推荐权重版本化 | Phase 4 | Procurement |
| 推荐方案评分权重 | price/time/reliability/risk 可配置 | Phase 6 | Sales/Product |
| Forecast 最小样本量与误差门槛 | 低样本不出细粒度预测 | Phase 6 | Data/Product |
| 聚合价格最小匿名样本量 | 未定；默认不外显 | Phase 6 | Security/Legal/Product |
| Dynamic Pricing 自动审批阈值 | MVP 默认所有外部发布人工批准 | Phase 10 | Sales/Finance |
| 数据保留期限 | 架构建议 7 年交易审计；待政策确认 | Phase 1/上线前 | Legal/Security |
| AI Provider 与数据驻留 | Provider-neutral port；未选择 | Phase 3 | Security/Tech |

## 架构验收清单

- [ ] 同意模块化单体 + Worker 的部署边界。
- [ ] 同意组织级 RBAC 和供应商任务隔离模型。
- [ ] 同意一个 `marketplace` schema 与 72 表 baseline。
- [ ] 同意 Plan/Supplier Quote/Customer Quote 不可变 revision。
- [ ] 同意 Order/Shipment 分离和多对多 allocation。
- [ ] 同意 Outbox/Inbox + RabbitMQ 至少一次投递。
- [ ] 同意 AI 候选 + 确定性 Guardrail + Review 的安全边界。
- [ ] 同意 Price Intelligence 的隐私、模型 Registry、Shadow 和审批边界。
- [ ] 同意现有 FastAPI/Vite 不在数据库阶段被删除或覆盖。
- [ ] 确认 Phase 1 只实施数据库、迁移、seed 和基础设施测试，不写业务功能。
