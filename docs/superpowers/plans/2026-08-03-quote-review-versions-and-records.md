# Quote Review Versions and Records Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把销售报价记录升级为拥有不可变 V1/V2/Vn、原子复核、对象级权限、清晰列表/详情和完整时间线的唯一业务主线。

**Architecture:** `SalesQuoteRecord` 保持聚合根并区分当前 locked version 与唯一 working draft。初次提交无论自动或人工都创建锁定 V1；自动成功 V1 可发送，人工/失败 V1 不可发送；运营基于明确版本创建新的锁定可发送版本，绝不覆盖。服务层持有事务边界、行锁、幂等和状态转换；销售与后台前端分别消费摘要/公开详情/内部复核 DTO。

**Tech Stack:** FastAPI、Pydantic 2、SQLAlchemy 2、PostgreSQL 行锁、Alembic、Pytest、React、TypeScript、Vitest、Testing Library。

---

## Task 1: 定义递归公开快照契约

**Files:**

- Create: `apps/api/schemas/quote_public.py`
- Create: `apps/api/services/public_quote_snapshot.py`
- Create: `tests/services/test_public_quote_snapshot.py`
- Modify: `packages/quote_engine/fcl.py`
- Modify: `packages/quote_engine/zone_models.py`

- [ ] 先写测试：在顶层、`fee_items`、`matched_rate_cards`、`metadata` 和嵌套对象中放入 `vendor`、`cost_unit_price`、`source`、`priority`、`rate_card_id`、`internal_note`、`exchange_source`，断言公开快照全部移除。
- [ ] 测试未知字段默认不公开，只有 schema 明确声明的字段存在。
- [ ] 测试金额序列化为十进制字符串，不转 JavaScript 浮点数。
- [ ] 运行并确认 PR #3 的 `dict.pop()` 黑名单无法通过嵌套测试。

```bash
pytest -q tests/services/test_public_quote_snapshot.py
```

- [ ] 用类型化 Pydantic 模型定义 `PublicFeeItem`、`PublicCargoSummary`、`PublicRouteSummary`、`PublicQuoteTotals`、`PublicQuoteSnapshot`，所有模型 `extra="forbid"`。
- [ ] `build_public_quote_snapshot` 从引擎结果显式构造每个字段，不复制任意内部字典。
- [ ] 加拿大末端和 FCL 共享费用、合计、公司和条款的公开 schema，但保留各自输入摘要类型。
- [ ] `PublicQuoteSnapshot.customer_name` 来自版本创建时冻结值，不在读取或 PDF 时重新 join 当前 Customer 名称。
- [ ] `snapshot_sha256` 使用 `json.dumps(..., sort_keys=True, separators=(",", ":"), ensure_ascii=False)` 的 UTF-8 字节计算。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/schemas/quote_public.py apps/api/services/public_quote_snapshot.py tests/services/test_public_quote_snapshot.py packages/quote_engine/fcl.py packages/quote_engine/zone_models.py
git commit -m "feat(quotes): define recursive public snapshot allowlist"
```

## Task 2: 新增不可变版本模型和历史回填

**Files:**

- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0025_quote_versions.py`
- Create: `apps/api/db/repositories/quote_version_repository.py`
- Modify: `apps/api/db/repositories/sales_quote_record_repository.py`
- Modify: `apps/api/db/repositories/manual_quote_task_repository.py`
- Modify: `tests/db/test_quote_lifecycle_constraints.py`
- Create: `tests/db/test_quote_version_repository.py`
- Create: `tests/migrations/test_0025_quote_versions.py`

- [ ] 先写模型/仓储测试：
  - `(record_id, version_no)` 唯一；
  - 锁定版本通过 repository、ORM `before_flush` 和 PostgreSQL trigger 任一路径修改都失败；
  - `current_version_id` 必须指向同一报价的 locked 版本，`working_version_id` 必须指向同一报价的 draft；
  - draft 必须 `sendable=false` 且 `locked_at IS NULL`；locked 必须有 `locked_at`，只有 locked 才能 `sendable=true`；
  - parent version、`ManualQuoteTask.quote_version_id/resolved_version_id` 必须属于同一报价；
  - 两个并发请求不能都创建 V2；
  - 客户改名后历史版本 `customer_name` 和快照不变；
  - 历史记录回填后每条至少有一个版本且哈希非空，无法判断的状态为 `legacy_unclassified` 而非默认待复核。
- [ ] 运行并确认模型缺失失败。

```bash
pytest -q tests/db/test_quote_lifecycle_constraints.py tests/db/test_quote_version_repository.py tests/migrations/test_0025_quote_versions.py
```

- [ ] 确认计划 1 已创建 `customer_id`，PR #3 的 `0022_quote_workflow` 已创建 `workflow_status/revision/valid_until/sent_at/closed_at`，不得重复加列；本迁移只继续扩展：
  - `owner_user_id`
  - `created_by_user_id`
  - `current_version_id`
  - `working_version_id`
- [ ] `owner_user_id` 表示负责该报价的人；`created_by_user_id` 表示真实操作人。管理员自行报价时两者均为管理员；未来替其他销售创建必须显式传入 owner 并保留真实创建人。
- [ ] 扩展既有 `QuoteWorkflowStatus` 枚举加入 `legacy_unclassified`，只用于无法由证据确定状态的旧记录；新建报价不能进入该状态。
- [ ] 新增 `QuoteVersion`：

```python
class QuoteVersion(Base):
    __tablename__ = "quote_versions"
    __table_args__ = (
        UniqueConstraint("record_id", "version_no", name="uq_quote_versions_record_version"),
        UniqueConstraint("id", "record_id", name="uq_quote_versions_id_record"),
        CheckConstraint("lifecycle IN ('draft', 'locked')", name="ck_quote_versions_lifecycle"),
        CheckConstraint("lifecycle = 'locked' OR sendable = false", name="ck_quote_versions_draft_not_sendable"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("sales_quote_records.id", ondelete="CASCADE"), nullable=False, index=True)
    parent_version_id: Mapped[int | None] = mapped_column(ForeignKey("quote_versions.id", ondelete="RESTRICT"))
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    lifecycle: Mapped[str] = mapped_column(String(16), nullable=False)
    version_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sendable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    customer_name: Mapped[str] = mapped_column(String(200), nullable=False)
    confirmed_fields_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    calculation_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    internal_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    public_snapshot_json: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)
    customer_reply: Mapped[str] = mapped_column(Text, nullable=False)
    valid_until: Mapped[date | None] = mapped_column(Date)
    snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_by_name: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_role: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    locked_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
```

- [ ] `QuoteVersion` 不保存模板或 renderer；这些只属于计划 5 的 `QuoteDocument`。draft 允许带 `version_revision` 编辑，locked 必须有 `locked_at/locked_by_user_id`，且锁定后所有业务字段不可变。
- [ ] 扩展 `ManualQuoteTask`：统一报价外键名为 `record_id`，增加 `quote_version_id`、`claimed_by_user_id`、`claimed_at`、`due_at`、`resolved_version_id`。
- [ ] 扩展 `QuoteWorkflowEvent`：`quote_version_id`、`manual_task_id`、`action_scope`、`idempotency_key`、`record_revision`；给 `(record_id, action_scope, idempotency_key)` 建唯一约束。
- [ ] 迁移先建版本表，再添加 `current_version_id/working_version_id`；使用复合外键或等价数据库约束保证 parent、record、current/working version 和 task version 同属一份报价，避免只依赖服务层校验。
- [ ] 增加 PostgreSQL trigger（SQLite 测试以 ORM `before_flush` 补充）禁止更新任何 locked 版本字段；测试绕过 repository 直接 ORM/SQL 更新快照、金额、哈希和 `sendable` 都失败。
- [ ] 回填前审计旧 `workflow_status`、任务、`sent_at`、结果字段和 actor 类型。只有证据充分才映射业务状态；actor 是 API key、缺失或无法确认负责人时允许 legacy owner 为空。无法判断的记录改为 `legacy_unclassified` 并写迁移异常清单，绝不能把 0022 默认 `pending_review` 当事实。
- [ ] 用稳定本地 allowlist 为每条旧记录创建 `source=legacy_backfill` 的 locked、默认 `sendable=false` 版本并冻结 `customer_name`；只有公开报价与发送证据完整时才可设为可发送/相应历史状态。回填数量必须等于旧销售记录数量。
- [ ] 保留 PR #3 旧字段以兼容读取，但新写路径不再把 `snapshot_json` 当当前报价事实来源。
- [ ] 仓储 `create_next_locked_version` 使用 `SELECT ... FOR UPDATE` 锁住 `SalesQuoteRecord`，从数据库最大版本号加 1，不接受前端传入版本号。
- [ ] `0025_quote_versions` 的 `down_revision` 固定为 `0024_fcl_rate_contracts`；该迁移创建并应用后禁止后续计划改写。
- [ ] 运行定向测试和 `alembic heads`，预期通过且只有 `0025_quote_versions`。
- [ ] 提交。

```bash
git add apps/api/db/models.py migrations/versions/0025_quote_versions.py apps/api/db/repositories/quote_version_repository.py apps/api/db/repositories/sales_quote_record_repository.py apps/api/db/repositories/manual_quote_task_repository.py tests/db tests/migrations/test_0025_quote_versions.py
git commit -m "feat(quotes): add immutable quote versions"
```

## Task 3: 原子创建初始 V1

**Files:**

- Create: `apps/api/services/quote_application_service.py`
- Modify: `apps/api/services/ai_quote_service.py`
- Modify: `apps/api/services/fcl_quote_service.py`
- Modify: `apps/api/services/quote_service.py`
- Modify: `apps/api/db/repositories/quote_audit_repository.py`
- Create: `tests/services/test_quote_application_service.py`
- Modify: `tests/api/test_ai_auto_quote.py`
- Modify: `tests/api/test_fcl_workflow.py`

- [ ] 先写服务测试：
  - 自动报价创建 record + locked/sendable V1 + current_version + event，状态 `ready_to_send`；
  - 需要人工的报价创建 record + locked/non-sendable V1 + manual task + event，状态 `pending_review`，V1 保留结构化输入、服务端计算值和失败原因；
  - audit 写入失败时全部回滚；
  - manual task 写入失败时 record 和 V1 也回滚；
  - 同一 `Idempotency-Key` 重复提交返回同一 record/V1。
  - V1 冻结提交时的 `customer_name`，之后重命名 Customer 不改变版本、详情或公开快照。
- [ ] 运行并确认现有 AI/FCL 服务多次 commit、吞异常或没有版本导致失败。

```bash
pytest -q tests/services/test_quote_application_service.py tests/api/test_ai_auto_quote.py tests/api/test_fcl_workflow.py
```

- [ ] `QuoteApplicationService.submit_initial_quote` 接收已经完成的确定性计算结果和真实 actor，在一个事务中：
  1. 创建 `SalesQuoteRecord`；
  2. 冻结 `customer_name` 并创建 locked V1；成功自动报价设 `sendable=true`，人工/失败尝试设 `sendable=false`；
  3. 设置 `current_version_id`、状态、valid_until；
  4. 需要人工时创建关联任务；
  5. 写 workflow event 和 audit；
  6. `flush` 后由服务统一 `commit`。
- [ ] repositories 只 `add/flush`，不自行 `commit`；服务捕获异常后 `rollback` 并重新抛出。
- [ ] AI 和 FCL 路由要求 `Idempotency-Key` header；请求体内的兼容幂等字段不作为权威。
- [ ] FCL 和加拿大末端人工任务都绑定不可发送 V1；自动 V1 也保留完整内部依据和公开快照。人工 V1 不能生成文档或发送。
- [ ] 运行定向测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/services/quote_application_service.py apps/api/services/ai_quote_service.py apps/api/services/fcl_quote_service.py apps/api/services/quote_service.py apps/api/db/repositories/quote_audit_repository.py tests/services/test_quote_application_service.py tests/api/test_ai_auto_quote.py tests/api/test_fcl_workflow.py
git commit -m "feat(quotes): persist initial quote version atomically"
```

## Task 4: 实现复核动作、V2/Vn 和并发保护

**Files:**

- Create: `apps/api/schemas/quote_lifecycle.py`
- Create: `apps/api/services/quote_version_service.py`
- Modify: `apps/api/services/quote_workflow_service.py`
- Modify: `apps/api/routes/manual_tasks.py`
- Modify: `apps/api/routes/sales_records.py`
- Create: `apps/api/services/quote_expiry_service.py`
- Create: `tests/services/test_quote_version_service.py`
- Create: `tests/services/test_quote_expiry_service.py`
- Create: `tests/api/test_quote_review_workflow.py`
- Modify: `tests/api/test_fcl_workflow.py`
- Create: `tests/api/test_final_mile_workflow.py`

- [ ] 分别写 FCL 和加拿大末端完整人工闭环测试：不可发送 V1 → 领取 → 要求补资料 → 销售补充 → 对应引擎重算并形成新锁定提交版本 → 重新进入复核 → 运营确认形成可发送 Vn → `ready_to_send`。加拿大末端必须重跑 `cargo_metrics` 和 Zone Quote Engine，确认勾选不能绕过声明冲突。
- [ ] 写并发测试：两个运营基于同一 `base_version_id` resolve，首个成功，第二个 `409 stale_quote_version`；不能生成两个相同版本号。
- [ ] 写回滚测试：新版本 flush 后模拟任务更新失败，断言版本、current_version、任务和事件全部未提交。
- [ ] 写权限测试：销售不能 claim/resolve，运营不能替销售提交客户发送，viewer 不能写。
- [ ] 写取消和到期测试：销售只可取消自己处于允许状态的报价；原因必填；过期 reconciliation job 幂等；与发送/复核并发时使用 record revision，只有一个动作成功，均写审计。
- [ ] 运行并确认 PR #3 直接改 `snapshot_json` 或缺少版本绑定而失败。

```bash
pytest -q tests/services/test_quote_version_service.py tests/services/test_quote_expiry_service.py tests/api/test_quote_review_workflow.py tests/api/test_fcl_workflow.py tests/api/test_final_mile_workflow.py
```

- [ ] `quote_lifecycle.py` 定义禁止额外字段的请求：
  - `ClaimReviewRequest`
  - `RequestSalesInfoRequest(required_fields, public_note, expected_revision)`
  - `ResolveReviewRequest(base_version_id, fee_items, manual_fx_inputs, settlement_currency, valid_until, public_note, customer_terms, customer_reply, internal_note, expected_revision)`
  - `RequestReReviewRequest(reason, expected_revision)`
  - `SubmitAdditionalInfoRequest(base_version_id, payload=FinalMileAdditionalInfo | FCLAdditionalInfo, expected_revision)`，按 `quote_type` discriminated union 校验
  - `CancelQuoteRequest(reason, expected_revision)`
- [ ] `manual_fx_inputs` 为类型化、可审计的源币种/目标币种/rate/effective_date/reason；`resolve` 从 `fee_items` 重新按币种聚合并派生 `totals_by_currency/converted_total`，再用公开 allowlist 构造 locked/sendable Vn。请求夹带 totals、converted total、`public_snapshot_json` 或状态返回 `422`；金额、币种和人工汇率不一致返回 `409`。
- [ ] `additional-info` 在同一报价上按类型调用对应的确定性计算和报价引擎，创建新 locked 提交版本并重新计算；不创建割裂的新 `SalesQuoteRecord`。
- [ ] 销售在 `ready_to_send` 申请重新复核时必须填写原因，创建绑定当前版本的新任务并进入 `pending_review`。
- [ ] 事务开始时锁 record 和 task，校验 `expected_revision`、`base_version_id` 和当前状态；不满足返回 `409`。
- [ ] 每次成功动作将 `revision += 1`，事件记录新 revision 和幂等键。
- [ ] 增加 `POST /quotes/sales-records/{record_id}/cancel`；到期服务只把到期且仍可推进的记录改为 `expired`，不覆盖 accepted/rejected/cancelled，并可安全重复执行。
- [ ] 运行定向测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/schemas/quote_lifecycle.py apps/api/services/quote_version_service.py apps/api/services/quote_workflow_service.py apps/api/services/quote_expiry_service.py apps/api/routes/manual_tasks.py apps/api/routes/sales_records.py tests/services/test_quote_version_service.py tests/services/test_quote_expiry_service.py tests/api/test_quote_review_workflow.py tests/api/test_fcl_workflow.py tests/api/test_final_mile_workflow.py
git commit -m "feat(review): create locked reviewed versions atomically"
```

## Task 5: 重建摘要、详情、版本和时间线 API

**Files:**

- Create: `apps/api/schemas/sales_quote_records.py`
- Create: `apps/api/schemas/admin_quote_records.py`
- Modify: `apps/api/routes/sales_records.py`
- Create: `apps/api/routes/admin_quotes.py`
- Modify: `apps/api/main.py`
- Modify: `apps/api/db/repositories/sales_quote_record_repository.py`
- Create: `apps/api/services/quote_read_service.py`
- Create: `tests/api/test_sales_quote_record_list.py`
- Create: `tests/api/test_sales_quote_record_detail.py`
- Create: `tests/api/test_sales_quote_record_rbac.py`
- Create: `tests/api/test_admin_quote_records.py`

- [ ] 先写列表测试：服务端分页、状态组、类型、日期、销售和关键词筛选；响应不含 `request_json/result_json/internal_snapshot`。
- [ ] 先写详情测试：包含概览、结构化询价、当前公开版本、版本摘要、公开时间线和 `allowed_actions`；销售不见内部备注。
- [ ] 写时间线泄露测试：在事件 metadata 多层嵌套供应商、成本、费率 ID、候选匹配、内部备注和收件信息；销售响应全部不存在，后台审计 DTO 在授权后按独立 schema 返回。
- [ ] 写对象级权限测试：销售查看他人记录、版本或时间线返回 `403`；后台有相应角色可看；viewer 只读。
- [ ] 写 N+1 查询保护测试或仓储查询断言，列表不为每一行读取完整版本 JSON。
- [ ] 写后台记录测试：一报价一行；多个版本只给摘要计数；详情公开区与内部区分离；viewer/operator/admin 权限不同；无原始 JSON。文档/发送区先返回稳定空摘要或经证据转换的 legacy 摘要，计划 5 接入正式实体。
- [ ] 运行并确认旧 `GET /sales-records` 返回数组和完整 JSON、后台记录接口缺失而失败。

```bash
pytest -q tests/api/test_sales_quote_record_list.py tests/api/test_sales_quote_record_detail.py tests/api/test_sales_quote_record_rbac.py tests/api/test_admin_quote_records.py
```

- [ ] 列表响应固定为：

```python
class SalesQuoteRecordListResponse(BaseModel):
    records: list[SalesQuoteRecordSummary]
    total: int
    limit: int
    offset: int
```

- [ ] 状态组由服务端映射：
  - `needs_action`: `needs_sales_info`, `ready_to_send`, `change_requested`
  - `in_progress`: `pending_review`, `in_review`, `sent`
  - `closed`: `accepted`, `rejected`, `expired`, `cancelled`
  - `legacy`: `legacy_unclassified`
- [ ] 详情接口：
  - `GET /quotes/sales-records/{record_id}`
  - `GET /quotes/sales-records/{record_id}/versions`
  - `GET /quotes/sales-records/{record_id}/versions/{version_no}`
  - `GET /admin/quotes`（后台一报价一行摘要）
  - `GET /admin/quotes/{record_id}`（公开区、内部区、嵌套版本/发送摘要与审计分区）
- [ ] `allowed_actions` 由服务端根据角色、状态、当前版本的 lifecycle/sendable、有效期和 revision 生成；非 `ready_to_send` 或不可发送版本绝不返回生成文档/发送动作，前端不硬编码状态机。
- [ ] 在 `sales_quote_records.py` 分别定义 `PublicTimelineEvent` 和 `AdminAuditEvent`，所有嵌套模型 `extra="forbid"`。销售事件类型 allowlist 固定为 `submitted/info_requested/info_submitted/version_ready/sent/accepted/change_requested/rejected/expired/cancelled`，字段只允许 `public_note`、actor 展示名和时间，不把任意 metadata 透传；后台详情通过独立受权端点读取内部审计字段。
- [ ] 后台摘要也按 record 分页，绝不 join 后直接把每个版本变成一行；详情为公开报价与内部计算分别使用类型化 DTO。预留 `document_count/send_count` 类型化字段但不伪造数据，计划 5 创建正式实体后再填充并对收件信息独立鉴权。
- [ ] 保留旧列表响应的短期兼容端点时放到 `/quotes/legacy/sales-records`，新前端不得调用。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/schemas/sales_quote_records.py apps/api/schemas/admin_quote_records.py apps/api/routes/sales_records.py apps/api/routes/admin_quotes.py apps/api/main.py apps/api/db/repositories/sales_quote_record_repository.py apps/api/services/quote_read_service.py tests/api/test_sales_quote_record_list.py tests/api/test_sales_quote_record_detail.py tests/api/test_sales_quote_record_rbac.py tests/api/test_admin_quote_records.py
git commit -m "feat(api): expose paginated quote summaries and version detail"
```

## Task 6: 重建运营复核工作台

**Files:**

- Replace: `apps/web/src/pages/ManualTasksPage.tsx`
- Modify: `apps/web/src/pages/OperationsWorkbenchPage.tsx`
- Create: `apps/web/src/pages/admin/ReviewQueuePage.tsx`
- Create: `apps/web/src/pages/admin/ReviewDetailPage.tsx`
- Create: `apps/web/src/features/review/ReviewHeader.tsx`
- Create: `apps/web/src/features/review/SystemCalculationPanel.tsx`
- Create: `apps/web/src/features/review/ReviewDecisionForm.tsx`
- Create: `apps/web/src/features/review/VersionDiff.tsx`
- Create: `apps/web/src/features/review/ReviewTimeline.tsx`
- Create: `apps/web/src/pages/admin/ReviewQueuePage.test.tsx`
- Create: `apps/web/src/pages/admin/ReviewDetailPage.test.tsx`
- Modify: `apps/web/src/api/reviews.ts`
- Modify: `apps/web/src/domain/quoteWorkflow.ts`

- [ ] 先写队列测试：按超时、到期、冲突、补资料重提、普通待处理排序；支持 quote、路线、客户、销售和处理人筛选。
- [ ] 写详情测试：头部先显示 Quote ID、销售、状态、提交时间、路线、柜型、当前合计、有效期和下一步；页面没有原始 JSON。
- [ ] 写动作测试：领取、要求补资料、确认版本、取消；确认表单提交 `{amount,currency}` 费用行和类型化人工换汇依据，不提交 `totals_by_currency/converted_total/resolved_price_usd`；服务端返回并显示权威合计。
- [ ] 写并发错误测试：`409` 后刷新当前版本并保留用户未提交的内部备注草稿，但不自动重试 resolve。
- [ ] 运行并确认旧 `ManualTasksPage` 失败。

```bash
cd apps/web
npm test -- --run src/pages/admin/ReviewQueuePage.test.tsx src/pages/admin/ReviewDetailPage.test.tsx
```

- [ ] `ReviewDecisionForm` 分成公开费用、人工换汇依据、服务端权威币种合计、有效期、客户条款、客户回复、公开说明、内部备注；本地合计只能标“预览”，提交成功后以 API 返回覆盖，公开和内部字段有明显视觉边界。
- [ ] 同步 `domain/quoteWorkflow.ts` 与后端枚举，加入只读的 `legacy_unclassified` 映射“历史待核对”；该状态不显示复核、生成 PDF 或发送动作。
- [ ] `VersionDiff` 只比较结构化公开字段，金额、路线、柜型、有效期和条款使用明确“旧值 → 新值”。
- [ ] 后台完成复核后只通知销售并显示“已生成 Vn，等待销售发送”，不出现发送客户邮件按钮。
- [ ] 移除旧邮件通知客户语义和 FCL 的“加拿大尾端派送”文案。
- [ ] 桌面采用队列 + 独立详情；移动端先列表后详情，不压缩成左右两栏。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/pages/ManualTasksPage.tsx apps/web/src/pages/OperationsWorkbenchPage.tsx apps/web/src/pages/admin apps/web/src/features/review apps/web/src/api/reviews.ts apps/web/src/domain/quoteWorkflow.ts
git commit -m "feat(web): rebuild operations review workbench"
```

## Task 7: 重建销售报价列表和详情

**Files:**

- Refactor: `apps/web/src/pages/QuotePage.tsx`
- Create: `apps/web/src/pages/sales/QuoteRecordsPage.tsx`
- Create: `apps/web/src/pages/sales/QuoteRecordDetailPage.tsx`
- Create: `apps/web/src/features/quotes/QuoteRecordTable.tsx`
- Create: `apps/web/src/features/quotes/QuoteRecordCard.tsx`
- Create: `apps/web/src/features/quotes/QuoteOverview.tsx`
- Create: `apps/web/src/features/quotes/QuoteInquirySnapshot.tsx`
- Create: `apps/web/src/features/quotes/PublicFeeTable.tsx`
- Create: `apps/web/src/features/quotes/QuoteVersionHistory.tsx`
- Create: `apps/web/src/features/quotes/QuoteActionBar.tsx`
- Create: `apps/web/src/pages/sales/QuoteRecordsPage.test.tsx`
- Create: `apps/web/src/pages/sales/QuoteRecordDetailPage.test.tsx`
- Modify: `apps/web/src/apps/SalesApp.tsx`
- Modify: `apps/web/src/api/salesQuotes.ts`
- Modify: `apps/web/src/domain/quotes.ts`
- Modify: `apps/web/src/domain/quoteWorkflow.ts`

- [ ] 先写列表测试：一条报价一行；V1/V2 不变成两条；桌面列和移动卡包含相同关键字段；筛选调用服务端参数。
- [ ] 写详情测试：先“现在该做什么”，再概览、询价、报价明细、版本与处理、时间线；FCL 不显示原始询价区。
- [ ] 写动作测试：只渲染 API `allowed_actions`；锁定版本没有价格编辑控件；申请重新复核必须填写原因。
- [ ] 写公开字段测试：组件收到带内部字段的恶意 fixture 时类型构造失败，DOM 中无供应商、成本、source、priority 或内部备注。
- [ ] 运行并确认旧 `QuotePage` 左右堆叠和客户端过滤失败。

```bash
cd apps/web
npm test -- --run src/pages/sales/QuoteRecordsPage.test.tsx src/pages/sales/QuoteRecordDetailPage.test.tsx
```

- [ ] 列表只调用摘要 API；打开详情才请求版本和时间线。
- [ ] 顶部和移动底部动作栏使用相同 `allowed_actions`，每个状态只突出一个主要动作。
- [ ] 版本历史显示版本号、来源、创建人、时间、有效期和是否当前；点击历史版本只读。
- [ ] 加拿大末端详情可折叠查看原始文本证据；FCL 只有结构化字段快照。
- [ ] 内部原因代码统一映射为中文说明和解决建议，不显示 `no_published_rate_card` 等原始代码。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/pages/QuotePage.tsx apps/web/src/pages/sales/QuoteRecordsPage.tsx apps/web/src/pages/sales/QuoteRecordDetailPage.tsx apps/web/src/features/quotes apps/web/src/apps/SalesApp.tsx apps/web/src/api/salesQuotes.ts apps/web/src/domain/quotes.ts apps/web/src/domain/quoteWorkflow.ts
git commit -m "feat(web): rebuild sales quote records and detail"
```

## Task 8: 重建后台报价记录和分区详情

**Files:**

- Create: `apps/web/src/pages/admin/AdminQuoteRecordsPage.tsx`
- Create: `apps/web/src/pages/admin/AdminQuoteDetailPage.tsx`
- Create: `apps/web/src/features/admin-quotes/AdminQuoteTable.tsx`
- Create: `apps/web/src/features/admin-quotes/AdminQuoteOverview.tsx`
- Create: `apps/web/src/features/admin-quotes/PublicQuoteSection.tsx`
- Create: `apps/web/src/features/admin-quotes/InternalReviewSection.tsx`
- Create: `apps/web/src/features/admin-quotes/NestedVersionSendHistory.tsx`
- Create: `apps/web/src/pages/admin/AdminQuoteRecordsPage.test.tsx`
- Create: `apps/web/src/pages/admin/AdminQuoteDetailPage.test.tsx`
- Modify: `apps/web/src/apps/AdminApp.tsx`
- Modify: `apps/web/src/api/adminQuotes.ts`
- Modify: `apps/web/src/domain/adminQuotes.ts`

- [ ] 先写列表测试：一份 `SalesQuoteRecord` 只出现一行；V1/V2/Vn 只显示版本计数，不展开成重复行；服务端按销售、处理人、状态、类型、日期和异常分页筛选。
- [ ] 写详情测试：按“概览 / 公开报价 / 内部计算与复核 / 版本历史 / 发送与客户结果 / 审计时间线”分区；公开费用与成本、供应商、内部说明不在同一表；页面不显示原始 JSON。
- [ ] 写权限测试：viewer 只读，operator/admin 按授权查看内部区；销售路由不能 import 后台组件；收件信息使用独立授权请求。
- [ ] 运行测试并确认仅有后台路由占位、没有实际页面而失败。

```bash
cd apps/web
npm test -- --run src/pages/admin/AdminQuoteRecordsPage.test.tsx src/pages/admin/AdminQuoteDetailPage.test.tsx
```

- [ ] 后台列表复用服务端后台摘要 DTO，而不是销售 DTO 加客户端拼接；版本只在打开详情后按需读取。文档/发送/结果区先呈现明确空状态，计划 5 接入正式接口后替换，不能用假数据。
- [ ] 移动端列表切换为同字段记录卡；详情各区纵向排列，内部区有明确权限标签和视觉边界。
- [ ] 将 `/admin/quotes` 与 `/admin/quotes/:recordId` 接入独立 AdminApp，不加入销售壳。
- [ ] 运行测试和构建，提交。

```bash
git add apps/web/src/pages/admin/AdminQuoteRecordsPage.tsx apps/web/src/pages/admin/AdminQuoteDetailPage.tsx apps/web/src/features/admin-quotes apps/web/src/apps/AdminApp.tsx apps/web/src/api/adminQuotes.ts apps/web/src/domain/adminQuotes.ts
git commit -m "feat(admin): organize quote records and nested history"
```

## Task 9: 版本与复核阶段回归

- [ ] 后端定向测试：

```bash
pytest -q tests/services/test_public_quote_snapshot.py tests/db/test_quote_lifecycle_constraints.py tests/db/test_quote_version_repository.py tests/migrations/test_0025_quote_versions.py tests/services/test_quote_application_service.py tests/services/test_quote_version_service.py tests/services/test_quote_expiry_service.py tests/api/test_quote_review_workflow.py tests/api/test_sales_quote_record_list.py tests/api/test_sales_quote_record_detail.py tests/api/test_sales_quote_record_rbac.py tests/api/test_admin_quote_records.py tests/api/test_fcl_workflow.py tests/api/test_final_mile_workflow.py
```

- [ ] 运行 API 全量回归：

```bash
pytest -q tests/api
```

- [ ] 前端测试和构建：

```bash
cd apps/web
npm test -- --run
npm run build
```

- [ ] 在 PostgreSQL 临时库验证 `0024 → 0025 → 0024 → 0025`，并核对回填与回滚：

```bash
cd ../..
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic upgrade 0025_quote_versions
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic downgrade 0024_fcl_rate_contracts
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic upgrade 0025_quote_versions
```

- [ ] 查询并确认 `sales_quote_records` 数量等于有初始版本的 distinct `record_id` 数量；current/working/task version 均属于自身；locked 版本不可 SQL 更新；`legacy_unclassified` 数量等于审计无法判定的旧记录数量。
- [ ] 运行两次并发 resolve 测试，确认一个成功、一个 `409`。
- [ ] 用销售账号尝试读取他人详情和历史版本，确认 `403`。
- [ ] `git diff --check`，继续执行计划 4 和计划 5；不合并、不部署。
