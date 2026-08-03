# Pricing Configuration and Management Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把后台价格维护改为任务驱动、可验证、可原子发布和可回滚的流程，并建立只反映商业报价结果的管理数据页面。

**Architecture:** FCL 配置与费率卡以不可变 release 一起发布；每个 scope 由单独的 release head 指向唯一当前版本，发布事务锁定 head 行，自动报价只读取该指针。维护任务服务持续生成到期、缺失和冲突任务，加拿大末端现有规则/矩阵保留但纳入同一维护入口。所有商业 KPI 默认以唯一 `SalesQuoteRecord` 为统计单位，报价版本、复核轮次和发送尝试仅作为独立流程指标；配置健康与运营积压不混入经营指标。

**Tech Stack:** SQLAlchemy 2、Alembic、PostgreSQL、FastAPI、Pydantic、Pytest、React、TypeScript、Vitest、Recharts。

---

## Task 1: 建立 FCL 不可变发布版本和 release

**Files:**

- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0026_fcl_pricing_releases.py`
- Modify: `apps/api/db/repositories/fcl_rate_card_repository.py`
- Create: `apps/api/db/repositories/fcl_pricing_release_repository.py`
- Create: `tests/db/test_fcl_pricing_release_repository.py`
- Modify: `tests/db/test_quote_rule_config_repository.py`
- Create: `tests/migrations/test_0026_fcl_pricing_releases.py`

- [ ] 先写仓储测试：
  - 每个 scope 有且只有一行 release head，且只能指向同 scope 的 published release；
  - 发布版本号递增且并发不重复；
  - 已发布配置和费率卡不可编辑；
  - 新草稿引用明确 base release；
  - 旧已发布配置和费率卡可回填为一个初始 release；
  - release 只读保留，即使后来停用；
  - `(scope, version)` 唯一，两个 scope 可以各自拥有 v1；
  - head 的 `revision` 使用乐观并发检查，发布事务同时对该 scope 的 head 行加 `FOR UPDATE`；
  - head 不能跨 scope 指向 release，retired release 不能成为 current。
- [ ] 运行并确认现有 key/value draft 和单卡 publish 无法通过。

```bash
pytest -q tests/db/test_fcl_pricing_release_repository.py tests/db/test_quote_rule_config_repository.py tests/migrations/test_0026_fcl_pricing_releases.py
```

- [ ] 新增 `FCLPricingRelease`：

```python
class FCLPricingRelease(Base):
    __tablename__ = "fcl_pricing_releases"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    config_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    rate_card_snapshot_json: Mapped[list[dict[str, object]]] = mapped_column(JSON, nullable=False)
    validation_result_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    test_quote_result_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    base_release_id: Mapped[int | None] = mapped_column(ForeignKey("fcl_pricing_releases.id", ondelete="RESTRICT"))
    published_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    published_by_name: Mapped[str | None] = mapped_column(String(128))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rollback_of_id: Mapped[int | None] = mapped_column(ForeignKey("fcl_pricing_releases.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        UniqueConstraint("scope", "version", name="uq_fcl_pricing_release_scope_version"),
        UniqueConstraint("id", "scope", name="uq_fcl_pricing_release_id_scope"),
    )


class FCLPricingReleaseHead(Base):
    __tablename__ = "fcl_pricing_release_heads"
    scope: Mapped[str] = mapped_column(String(128), primary_key=True)
    current_release_id: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    __table_args__ = (
        ForeignKeyConstraint(
            ["current_release_id", "scope"],
            ["fcl_pricing_releases.id", "fcl_pricing_releases.scope"],
            name="fk_fcl_pricing_head_release_same_scope",
            ondelete="RESTRICT",
        ),
        CheckConstraint("revision >= 0", name="ck_fcl_pricing_head_revision_nonnegative"),
    )
```

- [ ] `FCLQuoteConfigVersion` 增加 `status=draft|validated|published|retired`、`revision`、验证和测试结果；每次编辑草稿创建/更新明确的草稿行，不再把 `QuoteRuleConfig` key/value 当唯一 FCL 草稿。
- [ ] `FCLRateCard` 增加 `draft_revision`、`release_id`、`retired_at`、`superseded_by_id`；发布后拒绝 PATCH。
- [ ] release 保存 `scope` 对应的配置和费率卡完整不可变 JSON 快照，避免历史报价查询后来变化的表行；数据库约束和仓储校验共同禁止 head 指向不同 scope 或非 published release。
- [ ] 创建新迁移 `0026_fcl_pricing_releases.py`，`down_revision = "0025_quote_versions"`；禁止修改已经应用的 `0023`、`0024` 或 `0025`。迁移把每个 scope 当前 `fcl_quote_config_published` 和 `status=published` 的费率卡复制为 release v1，并为该 scope 创建 head；没有发布配置时不创建虚假 release/head。
- [ ] `get_published(scope)` 只通过 `FCLPricingReleaseHead.current_release_id` 返回该 scope 的 current published release；不存在时返回 `None`，不得返回 `default_fcl_quote_config()`，也不得用 `ORDER BY version DESC` 猜测 current。
- [ ] 在临时 PostgreSQL 验证 `0025 → 0026 → 0025 → 0026`，核对回填、约束和唯一 head 均可逆；运行测试和 `alembic heads`，预期唯一 head 为 `0026_fcl_pricing_releases`。
- [ ] 提交。

```bash
git add apps/api/db/models.py migrations/versions/0026_fcl_pricing_releases.py apps/api/db/repositories/fcl_rate_card_repository.py apps/api/db/repositories/fcl_pricing_release_repository.py tests/db/test_fcl_pricing_release_repository.py tests/db/test_quote_rule_config_repository.py tests/migrations/test_0026_fcl_pricing_releases.py
git commit -m "feat(config): add immutable FCL pricing releases"
```

## Task 2: 建立发布验证器和结构化测试报价

**Files:**

- Create: `apps/api/services/fcl_pricing_validation_service.py`
- Create: `apps/api/schemas/pricing_validation.py`
- Create: `tests/services/test_fcl_pricing_validation_service.py`
- Create: `tests/services/test_fcl_pricing_security_validation.py`
- Modify: `packages/quote_engine/fcl.py`

- [ ] 先写验证测试，逐项锁定阻断规则：
  - 费率生效区间无效；
  - 完整适用范围完全相同的两条费率只要有效期重叠就必须阻断，不能用 `priority` 消除冲突；完整适用范围至少包含 scope、路线、柜型、服务范围、船东、服务、特殊货物适用/排除集合和结算币种；
  - 部分范围相交但无法唯一选出费率时同样阻断，只有适用范围本身严格互斥才允许共存；
  - 汇率重叠或过期；
  - `per_shipment` 无稳定 fee ID 或重复定义冲突；
  - `markup_fixed` 无结算币种；
  - 特殊货物适用/排除范围矛盾；
  - `merged` 无真实合并目标；
  - `service_stages` 无真实计价实现；
  - 公开费用字段包含内部来源；
  - 报价有效期会超过底层费率/汇率；
  - 缺少目标 ETD 的测试报价不得通过自动报价验证。
- [ ] 运行并确认验证器不存在而失败。

```bash
pytest -q tests/services/test_fcl_pricing_validation_service.py tests/services/test_fcl_pricing_security_validation.py
```

- [ ] `PricingValidationResult` 返回 `valid`、`blocking_errors`、`warnings`、`tested_at`、`config_revision`、`rate_card_revisions` 和结构化测试报价摘要。
- [ ] 冲突检测先规范化完整适用范围和集合顺序，再比较时间区间；对完整适用范围相同且时间重叠的记录一律返回 blocking error，`priority` 只可用于展示或兼容读取，不能作为发布消歧规则。
- [ ] 测试报价使用固定的显式表单 fixture，不读取今天日期或默认客户数据；至少覆盖 20GP、40HQ、混合柜型、多币种和特殊货物。
- [ ] 如果首期不支持 `merged` 或 `service_stages`，验证器对其返回 blocking error；前端不展示这些选项。
- [ ] 验证公开快照时调用 `build_public_quote_snapshot` 并递归检查禁止字段。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/services/fcl_pricing_validation_service.py apps/api/schemas/pricing_validation.py tests/services/test_fcl_pricing_validation_service.py tests/services/test_fcl_pricing_security_validation.py packages/quote_engine/fcl.py
git commit -m "feat(config): validate pricing releases with structured quotes"
```

## Task 3: 实现保存、验证、原子发布、停用与回滚 API

**Files:**

- Modify: `apps/api/routes/quote_configs.py`
- Create: `apps/api/services/fcl_pricing_release_service.py`
- Modify: `apps/api/db/repositories/fcl_pricing_release_repository.py`
- Create: `tests/api/test_fcl_pricing_release_api.py`
- Create: `tests/services/test_fcl_pricing_release_service.py`
- Modify: `tests/api/test_quote_configs.py`

- [ ] 先写 API 测试：
  - 保存草稿返回 revision；
  - 修改未保存时不能发布旧版本；
  - 只有验证过的同一 revision 能发布；
  - 批量费率发布全成或全败；
  - 两管理员并发发布，一个成功、一个 `409`；
  - 紧急停用和回滚必须给原因并记录 actor；
  - operator 可以创建/编辑/保存/验证草稿并执行结构化测试报价，但发布、停用和回滚均为 `403`；
  - admin 可以执行草稿动作以及发布、停用和回滚；viewer 对列表、详情和验证结果只读，所有写操作为 `403`；sales 对定价配置 API 为 `403`。
- [ ] 写事务失败测试：发布中任一费率写入失败时 current release 和所有费率状态不变。
- [ ] 运行并确认现有 `/fcl/publish` 与单卡 publish 无法满足原子条件。

```bash
pytest -q tests/api/test_fcl_pricing_release_api.py tests/services/test_fcl_pricing_release_service.py tests/api/test_quote_configs.py
```

- [ ] API 固定为：
  - `POST /quote-configs/fcl/drafts`
  - `PATCH /quote-configs/fcl/drafts/{draft_id}`，带 `expected_revision`
  - `POST /quote-configs/fcl/drafts/{draft_id}/validate`
  - `POST /quote-configs/fcl/drafts/{draft_id}/test-quotes`
  - `POST /quote-configs/fcl/drafts/{draft_id}/publish`
  - `POST /quote-configs/fcl/releases/{release_id}/disable`
  - `POST /quote-configs/fcl/releases/{release_id}/rollback`
  - `GET /quote-configs/fcl/releases`
- [ ] 草稿和 test-quote 服务统一执行角色矩阵：operator/admin 可改草稿、保存、验证和测试；只有 admin 可发布、停用和回滚；viewer 只能 GET。每个允许/拒绝组合都在 `test_fcl_pricing_release_api.py` 中有断言。
- [ ] 发布服务对 `FCLPricingReleaseHead(scope)` 行加 `FOR UPDATE`，重新校验 draft revision、validation hash 和 `expected_head_revision`，在一个事务中创建 release、冻结费率、更新 head 指针及 revision、退休旧 current、写审计；不通过查询最大版本号代替锁。
- [ ] 回滚不是把旧行改回 published，而是从旧 release 快照创建一个新的发布版本，`rollback_of_id` 指向来源。
- [ ] 旧 `/fcl/publish` 和 `/{rate_card_id}/publish` 标记 deprecated 并拒绝新前端调用；稳定期后删除。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/routes/quote_configs.py apps/api/services/fcl_pricing_release_service.py apps/api/db/repositories/fcl_pricing_release_repository.py tests/api/test_fcl_pricing_release_api.py tests/services/test_fcl_pricing_release_service.py tests/api/test_quote_configs.py
git commit -m "feat(config): publish pricing releases atomically"
```

## Task 4: 建立定价维护任务

**Files:**

- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0027_pricing_maintenance_tasks.py`
- Create: `apps/api/db/repositories/pricing_maintenance_task_repository.py`
- Create: `apps/api/services/pricing_maintenance_service.py`
- Create: `apps/api/routes/pricing_maintenance.py`
- Modify: `apps/api/main.py`
- Create: `tests/services/test_pricing_maintenance_service.py`
- Create: `tests/api/test_pricing_maintenance_tasks.py`
- Create: `tests/migrations/test_0027_pricing_maintenance_tasks.py`

- [ ] 先写 reconciliation 测试：即将到期、已过期仍启用、缺路线、缺柜型、重叠费率、汇率缺失/冲突、特殊货物范围缺失、草稿未验证、验证未发布和测试报价失败分别生成稳定 fingerprint 的任务。
- [ ] 测试重复 reconcile 更新同一开放任务而不重复创建；问题消失后自动标记 resolved；人工确认忽略需有原因和审计。
- [ ] 测试任务有 owner、priority、due_at、status 和 resolution；operator 可领取、编辑、保存、验证和执行测试报价，但不能发布/停用/回滚；viewer 只能读取任务；admin 拥有全部权限。
- [ ] 运行并确认模型和服务不存在而失败。

```bash
pytest -q tests/services/test_pricing_maintenance_service.py tests/api/test_pricing_maintenance_tasks.py tests/migrations/test_0027_pricing_maintenance_tasks.py
```

- [ ] 新增 `PricingMaintenanceTask`：`scope`、`task_type`、`fingerprint`、`severity`、`title`、`description`、`affected_entities_json`、`status`、`assigned_to_user_id`、`due_at`、`resolution_note`、时间戳；开放任务 fingerprint 唯一。
- [ ] 创建新迁移 `0027_pricing_maintenance_tasks.py`，`down_revision = "0026_fcl_pricing_releases"`；禁止回改任何已应用迁移。使用 PostgreSQL partial unique index 保证同一 `(scope, fingerprint)` 最多一条开放任务，并为 `status`、`assigned_to_user_id`、`due_at` 增加查询索引。
- [ ] `reconcile_pricing_maintenance_tasks` 扫描 FCL release、费率、汇率、Zone 城市规则、Zone 价格矩阵和配置，不扫描客户数据。
- [ ] API：
  - `GET /pricing-maintenance/tasks`
  - `POST /pricing-maintenance/tasks/reconcile`
  - `POST /pricing-maintenance/tasks/{id}/claim`
  - `POST /pricing-maintenance/tasks/{id}/resolve`
- [ ] operator 可读取、领取、编辑任务，并沿任务入口保存/验证/测试关联草稿；只有 admin 能发布、停用和回滚 release；viewer 只读。API 测试逐项覆盖允许和 `403`，不能只测前端隐藏按钮。
- [ ] 在临时 PostgreSQL 验证 `0026 → 0027 → 0026 → 0027`，并断言降级只移除维护任务结构、不破坏 0026 release/head 数据；`alembic heads` 预期唯一 head 为 `0027_pricing_maintenance_tasks`。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/db/models.py migrations/versions/0027_pricing_maintenance_tasks.py apps/api/db/repositories/pricing_maintenance_task_repository.py apps/api/services/pricing_maintenance_service.py apps/api/routes/pricing_maintenance.py apps/api/main.py tests/services/test_pricing_maintenance_service.py tests/api/test_pricing_maintenance_tasks.py tests/migrations/test_0027_pricing_maintenance_tasks.py
git commit -m "feat(config): add task-driven pricing maintenance"
```

## Task 5: 重建后台“规则与价格”页面

**Files:**

- Replace: `apps/web/src/pages/FclSettingsPage.tsx`
- Refactor: `apps/web/src/pages/PricingSettingsPage.tsx`
- Refactor: `apps/web/src/pages/CitySettingsPage.tsx`
- Create: `apps/web/src/pages/admin/PricingWorkspacePage.tsx`
- Create: `apps/web/src/features/pricing/MaintenanceTaskList.tsx`
- Create: `apps/web/src/features/pricing/PricingDraftEditor.tsx`
- Create: `apps/web/src/features/pricing/ValidationResults.tsx`
- Create: `apps/web/src/features/pricing/StructuredTestQuote.tsx`
- Create: `apps/web/src/features/pricing/ReleaseHistory.tsx`
- Create: `apps/web/src/pages/admin/PricingWorkspacePage.test.tsx`
- Modify: `apps/web/src/apps/AdminApp.tsx`
- Modify: `apps/web/src/api/pricing.ts`

- [ ] 先写页面测试：默认首屏是维护任务，不是完整费率表；“基础数据”只作为数据维护二级页；未保存草稿显示明确状态。
- [ ] 写发布流程测试：保存 → 验证 → 结构化测试报价 → 发布；任何一步 revision 变化后发布按钮禁用。
- [ ] 写已发布 release 只读、创建新草稿、停用和回滚二次确认测试。
- [ ] 写移动端测试：任务卡保留严重程度、影响、负责人、截止时间和主动作。
- [ ] 运行并确认现有设置页直接编辑/发布行为失败。

```bash
cd apps/web
npm test -- --run src/pages/admin/PricingWorkspacePage.test.tsx
```

- [ ] 页面层级固定：维护任务 / FCL / 加拿大末端 / 数据维护 / 发布历史。
- [ ] `PricingDraftEditor` 维护 `serverRevision` 和 `dirty`；发布请求始终携带最后保存并验证的 revision。
- [ ] `ValidationResults` 按阻断错误和警告分组，每项显示受影响实体和修复入口。
- [ ] `StructuredTestQuote` 使用与销售 FCL 表单相同的字段 schema，但独立 fixture，不提供文本解析。
- [ ] 发布成功后自动刷新任务和 release 历史；失败不清空草稿。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/pages/FclSettingsPage.tsx apps/web/src/pages/PricingSettingsPage.tsx apps/web/src/pages/CitySettingsPage.tsx apps/web/src/pages/admin/PricingWorkspacePage.tsx apps/web/src/features/pricing apps/web/src/apps/AdminApp.tsx apps/web/src/api/pricing.ts
git commit -m "feat(admin): rebuild rules and pricing as maintenance tasks"
```

## Task 6: 建立商业管理指标 API

**Files:**

- Create: `apps/api/schemas/quote_metrics.py`
- Create: `apps/api/services/quote_metrics_service.py`
- Create: `apps/api/routes/quote_metrics.py`
- Modify: `apps/api/main.py`
- Create: `tests/services/test_quote_metrics_service.py`
- Create: `tests/api/test_quote_metrics.py`

- [ ] 先写固定数据集测试，精确验证：报价量、自动报价率、人工复核率、发送率、客户接受率、首次响应、复核、发送和客户结果耗时；同一记录增加 V2/V3、多轮复核和多次发送后，任何商业 KPI 的报价样本数都不得增加。
- [ ] 测试接受率分母只含已有最终结果的 accepted/rejected，不含暂无回复。
- [ ] 测试金额按币种分开；没有合法冻结汇率时不生成跨币种合计。
- [ ] 测试每个商业指标的 `dedup_key` 固定为 `SalesQuoteRecord.id`，销售绩效按 `owner_user_id` 归属而不是创建/复核/发送 actor；多版本、多次成功发送和重复工作流事件先按明确选择规则归一为一行 record。
- [ ] 测试 `version_count`、`review_round_count`、`send_attempt_count` 只出现在 `process_metrics`，且明确使用各自的 `QuoteVersion.id`、review event id、`QuoteSendEvent.id`；它们不能混入报价量、漏斗或销售商业绩效。
- [ ] 测试配置健康、维护任务和复核积压字段不出现在管理指标响应。
- [ ] 测试 sales 无权限看团队管理指标，operator/viewer/admin 按授权只读。
- [ ] 运行并确认服务不存在而失败。

```bash
pytest -q tests/services/test_quote_metrics_service.py tests/api/test_quote_metrics.py
```

- [ ] API 响应包含 `period`、`sample_sizes`、`definitions`、`summary`、`trend`、`funnel`、`loss_reasons`、`sales_performance` 和单独的 `process_metrics`；每项 definition 返回人口范围、时间字段、分子、分母、`dedup_key` 和事件选择规则。
- [ ] 所有时间区间使用用户选择时区归一化到 UTC 查询；默认过去 30 天，最大 366 天。
- [ ] 商业 KPI 默认先构造一行一报价的 record cohort，并固定去重规则：
  - 报价量：`COUNT(DISTINCT SalesQuoteRecord.id)`，以 record 的首次 submitted 时间入组；
  - 自动报价率：分子为在首次 `ready_to_send` 前没有人工复核事件的唯一 record，分母为已 submitted 的唯一 record；
  - 人工复核率：分子为至少有一次 review-requested 事件的唯一 record，分母为已 submitted 的唯一 record；
  - 发送率：分子为至少有一次 `QuoteSendEvent.status=succeeded` 的唯一 record，分母为达到 `ready_to_send` 的唯一 record；
  - 接受率：每个 record 只取按 `occurred_at, id` 排序的最新 accepted/rejected 终态，分母只含这两类已有终态的唯一 record；
  - 失单原因：每个 rejected record 只取同一最新终态的一条 reason；
  - 金额：每个 record 每项指标只选一份明确绑定版本快照（quoted 只用首次 locked/sendable version，sent 用首次成功发送所绑定版本，accepted 用终态绑定版本），再按币种聚合；locked/non-sendable 尝试没有客户报价金额，禁止按版本行直接求和。
- [ ] 首次响应、复核、发送和客户结果耗时也以 `SalesQuoteRecord.id` 去重，每个 record 分别选择首次提交到首次 locked/sendable version、首次 review-requested 到其对应 resolve、首次 ready-to-send 到首次成功发送、首次成功发送到最新终态作为单一样本；缺任一端时间的 record 不进入该耗时分母并返回样本数。
- [ ] 漏斗固定为：submitted → ready_to_send → sent → final_outcome → accepted，每阶段都是 `COUNT(DISTINCT SalesQuoteRecord.id)`；版本数、复核轮次和发送尝试数只能作为旁列 process metric。
- [ ] 销售绩效按 `SalesQuoteRecord.owner_user_id` 归属，同时显示唯一报价数量和 record 级时效，不以单一接受率排名小样本；返回每项分母与样本数。
- [ ] 注册 `quote_metrics_router`。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/schemas/quote_metrics.py apps/api/services/quote_metrics_service.py apps/api/routes/quote_metrics.py apps/api/main.py tests/services/test_quote_metrics_service.py tests/api/test_quote_metrics.py
git commit -m "feat(metrics): add auditable commercial quote metrics"
```

## Task 7: 建立管理数据页面和可视化

**Files:**

- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/src/pages/admin/ManagementDataPage.tsx`
- Create: `apps/web/src/features/metrics/MetricDefinitionDrawer.tsx`
- Create: `apps/web/src/features/metrics/QuoteTrendChart.tsx`
- Create: `apps/web/src/features/metrics/QuoteFunnel.tsx`
- Create: `apps/web/src/features/metrics/LossReasonChart.tsx`
- Create: `apps/web/src/features/metrics/SalesPerformanceTable.tsx`
- Create: `apps/web/src/pages/admin/ManagementDataPage.test.tsx`
- Modify: `apps/web/src/apps/AdminApp.tsx`
- Modify: `apps/web/src/api/management.ts`

- [ ] 安装 Recharts 并锁定到 `package-lock.json`。

```bash
cd apps/web
npm install recharts
```

- [ ] 先写页面测试：每个指标显示时间范围、样本数和口径；多币种金额分开；页面不出现配置健康或复核积压。
- [ ] 写去重展示测试：商业卡片、趋势、漏斗和销售绩效标明“按唯一报价记录”；版本数、复核轮次和发送尝试放在独立“流程效率”区域，不能与报价量并列相加或共用商业转化率。
- [ ] 写图表可访问性测试：图表有描述标题、可见图例、对应数据表或明细入口；失单原因按数量降序。
- [ ] 写空数据和单样本测试，不能显示误导性的百分比趋势。
- [ ] 运行并确认页面不存在而失败。

```bash
npm test -- --run src/pages/admin/ManagementDataPage.test.tsx
```

- [ ] `QuoteTrendChart` 最多同时显示报价、已发送、已接受三条线，图例可见。
- [ ] `QuoteFunnel` 显示每阶段数量和相对上一步转化率，不用漏斗面积暗示金额。
- [ ] `LossReasonChart` 使用横向条形图；长中文标签完整显示。
- [ ] `SalesPerformanceTable` 为主视图，默认按已发送量降序；接受率旁显示分母。
- [ ] 所有图表均可切换查看支撑表格；不把图表截图作为唯一信息来源。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/src/pages/admin/ManagementDataPage.tsx apps/web/src/features/metrics apps/web/src/apps/AdminApp.tsx apps/web/src/api/management.ts
git commit -m "feat(admin): add commercial quote management dashboard"
```

## Task 8: 配置与管理数据阶段回归

- [ ] 运行后端定向测试。

```bash
pytest -q tests/db/test_fcl_pricing_release_repository.py tests/migrations/test_0026_fcl_pricing_releases.py tests/services/test_fcl_pricing_validation_service.py tests/services/test_fcl_pricing_security_validation.py tests/services/test_fcl_pricing_release_service.py tests/api/test_fcl_pricing_release_api.py tests/services/test_pricing_maintenance_service.py tests/api/test_pricing_maintenance_tasks.py tests/migrations/test_0027_pricing_maintenance_tasks.py tests/services/test_quote_metrics_service.py tests/api/test_quote_metrics.py
```

- [ ] 运行 FCL 和 Zone 回归。

```bash
pytest -q tests/quote-engine/test_fcl_quote_engine.py tests/api/test_fcl_quotes.py tests/api/test_quote_configs.py tests/api/test_zone_quotes.py tests/db/test_quote_rule_config_repository.py tests/db/test_rate_rule_repository.py
```

- [ ] 前端测试和构建。

```bash
cd apps/web
npm test -- --run
npm run build
```

- [ ] 在临时 PostgreSQL 并发执行两次同一草稿发布，确认一个成功、一个 `409`，current release 唯一。
- [ ] 在临时 PostgreSQL 分别验证 `0025 → 0026 → 0025 → 0026` 和 `0026 → 0027 → 0026 → 0027`；本计划不做整条 `0022 → head` 降级，完整迁移链由总计划最终验证。
- [ ] 用一个即将到期 release 执行 reconcile，确认任务生成；创建替代 release 后再次 reconcile，确认任务解决。
- [ ] 核对管理数据的一个固定 30 天样本，金额没有跨币种误加。
- [ ] `git diff --check`，继续计划 5；不合并、不部署。
