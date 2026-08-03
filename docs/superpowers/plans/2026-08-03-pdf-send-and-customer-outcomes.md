# PDF Send and Customer Outcomes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `quote-pdf-builder` 的报价单版式与预览方式安全移植到主系统，并让版本绑定的 PDF、每次发送、跟进和客户结果形成完整可审计闭环。

**Architecture:** 后端只从记录的当前、锁定、可发送且未过期 `QuoteVersion.public_snapshot_json` 渲染不可变 HTML/PDF，文件和哈希持久化；模板 key 由服务端注册表解析，模板与 renderer 版本只冻结在 `QuoteDocument`，不写回报价版本。在线发送以持久化 pending outbox/lease 驱动，渠道调用和数据库确认可恢复但同一幂等键绝不再次调用渠道；线下发送由销售明确登记。客户结果绑定成功发送事件和准确版本，变更请求先创建不切换 current 的 working draft，重新提交后才由服务端引擎决定可发送或进入复核。

**Tech Stack:** Jinja2、Playwright Chromium、FastAPI、SQLAlchemy、Alembic、本地持久卷存储抽象、SMTP、Pytest、React、TypeScript、Vitest、Playwright Test。

---

## Task 1: 固定 PDF 移植来源和边界

**Files:**

- Create: `docs/QUOTE_PDF_PORT.md`
- Modify: `pyproject.toml`
- Modify: `apps/api/Dockerfile`
- Modify: `infra/docker-compose.yml`
- Modify: `infra/docker-compose.prod.yml`

- [ ] 在 `docs/QUOTE_PDF_PORT.md` 记录固定来源：
  - 仓库：`zqj372-ops/quote-pdf-builder`
  - 提交：`0b6e439f4203b3fc3159ca7ef613a3e51a1afc09`
  - 参考文件：
    - `src/modules/quotePdf/pdf/QuotePdfDocument.ts`
    - `src/modules/quotePdf/components/QuotePdfPreview.tsx`
    - `src/modules/quotePdf/utils/formatCurrency.ts`
    - `src/modules/quotePdf/types/quotePdf.ts`
- [ ] 文档明确只迁移 A4 信息层级、表格样式、预览方式和格式化语义；不迁移 Electron、localStorage、账单、可编辑 PDF 数据、JSON 导入导出和前端总计。
- [ ] 在 `pyproject.toml` 增加受控依赖：`jinja2>=3.1,<4.0`、`playwright>=1.50,<2.0`。
- [ ] 在 API Dockerfile 安装 Chromium 和依赖：

```dockerfile
RUN pip install --no-cache-dir -e . && python -m playwright install --with-deps chromium
```

- [ ] 配置：
  - `QUOTE_DOCUMENT_STORAGE_DIR=/app/outputs/quote_documents`
  - `QUOTE_DOCUMENT_MAX_BYTES=10485760`
  - `QUOTE_PDF_RENDER_TIMEOUT_MS=30000`
- [ ] 开发和生产 compose 都挂载 `/app/outputs`；生产已有 `../outputs:/app/outputs` 时只增加环境变量，不复制第二个卷。
- [ ] 运行镜像构建，确认 Chromium 安装成功。

```bash
docker build -f apps/api/Dockerfile -t ai-quote-api:pdf-test .
```

- [ ] 提交。

```bash
git add docs/QUOTE_PDF_PORT.md pyproject.toml apps/api/Dockerfile infra/docker-compose.yml infra/docker-compose.prod.yml
git commit -m "build(pdf): add pinned server PDF rendering dependencies"
```

## Task 2: 新增文档模型、存储抽象和约束

**Files:**

- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0028_quote_documents.py`
- Create: `apps/api/storage/quote_documents.py`
- Create: `apps/api/db/repositories/quote_document_repository.py`
- Create: `tests/storage/test_quote_document_storage.py`
- Create: `tests/db/test_quote_document_repository.py`
- Modify: `tests/db/test_quote_lifecycle_constraints.py`
- Create: `tests/migrations/test_0028_quote_documents.py`

- [ ] 先写测试：路径穿越被拒绝；原子写入使用临时文件后 rename；大小限制生效；同一版本/模板/快照/幂等键只生成一份；文档不能绑定其他报价的版本；删除报价不级联删除已发送文档；模板和 renderer 版本只存在于 `QuoteDocument`，`QuoteVersion` 不增加或冻结这两个字段。
- [ ] 运行并确认模型和存储不存在而失败。

```bash
pytest -q tests/storage/test_quote_document_storage.py tests/db/test_quote_document_repository.py tests/db/test_quote_lifecycle_constraints.py tests/migrations/test_0028_quote_documents.py
```

- [ ] 定义存储协议：

```python
class QuoteDocumentStorage(Protocol):
    def put(self, key: str, content: bytes) -> StoredDocument: ...
    def open(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
```

- [ ] `LocalQuoteDocumentStorage` 只接受服务端生成的 UUID key，校验解析后的路径始终位于配置根目录；先写临时文件、fsync、再原子 rename。
- [ ] 新增 `QuoteDocument`：

```python
class QuoteDocument(Base):
    __tablename__ = "quote_documents"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    quote_version_id: Mapped[int] = mapped_column(ForeignKey("quote_versions.id", ondelete="RESTRICT"), nullable=False, index=True)
    document_type: Mapped[str] = mapped_column(String(32), nullable=False, default="quote_pdf")
    template_key: Mapped[str] = mapped_column(String(64), nullable=False)
    template_version: Mapped[str] = mapped_column(String(64), nullable=False)
    renderer_version: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_backend: Mapped[str] = mapped_column(String(32), nullable=False, default="local")
    storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    html_storage_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    html_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version_snapshot_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
```

- [ ] 唯一约束覆盖 `(quote_version_id, template_key, template_version, version_snapshot_sha256, idempotency_key)`；另存规范化请求哈希，相同幂等键但模板 key 不同返回 `409`，不能生成第二份文档。
- [ ] 创建新迁移 `0028_quote_documents.py`，`down_revision = "0027_pricing_maintenance_tasks"`；禁止修改已应用的 `0023`–`0027`。迁移只创建 QuoteDocument 及其索引/约束，不给 `QuoteVersion` 增加 template/renderer 字段。
- [ ] 数据库提交失败时删除刚写入的孤儿临时文件；已成功数据库记录的文件不由普通回滚删除。
- [ ] 在临时 PostgreSQL 验证 `0027 → 0028 → 0027 → 0028`，确认降级只删除文档结构且 0027 数据不变；`alembic heads` 预期唯一 head 为 `0028_quote_documents`。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/db/models.py migrations/versions/0028_quote_documents.py apps/api/storage/quote_documents.py apps/api/db/repositories/quote_document_repository.py tests/storage tests/db/test_quote_document_repository.py tests/db/test_quote_lifecycle_constraints.py tests/migrations/test_0028_quote_documents.py
git commit -m "feat(pdf): persist version-bound quote documents"
```

## Task 3: 服务端渲染公开快照 HTML 和 PDF

**Files:**

- Create: `apps/api/templates/quote_document_v1.html`
- Create: `apps/api/services/quote_template_registry.py`
- Create: `apps/api/services/quote_document_renderer.py`
- Create: `apps/api/services/quote_document_service.py`
- Create: `tests/services/test_quote_document_renderer.py`
- Create: `tests/services/test_quote_document_service.py`
- Create: `tests/fixtures/public_quote_snapshot.json`

- [ ] 先写 renderer 测试：
  - 只接受 `PublicQuoteSnapshot`；
  - HTML 转义客户名、备注和条款；
  - A4、品牌头、客户、路线、费用、原币小计、合法折算总计、备注和条款存在；
  - 不调用任何金额计算函数；
  - HTML 不包含 internal/vendor/cost/source/priority/rate card；
  - Chromium 输出以 `%PDF-` 开头。
- [ ] 先写 service 测试：workflow 不是 `ready_to_send`、非 current 版本、草稿版本、locked 但 `sendable=false`、过期版本和快照哈希不一致均拒绝；尤其 `pending_review` 的 V1 即使 locked 也不能生成 PDF。渲染失败不创建 DB 记录；相同幂等键返回原文档且不再次渲染。
- [ ] 运行并确认模板/服务不存在而失败。

```bash
pytest -q tests/services/test_quote_document_renderer.py tests/services/test_quote_document_service.py
```

- [ ] 把 `QuotePdfDocument.ts` 的 A4 布局和 CSS 译为 Jinja 模板，但改为直接读取公开快照中的 `amount`、`totals_by_currency`、`converted_total`；绝不使用 `quantity × unit_price` 重算正式金额。
- [ ] 模板只展示公开快照已经允许的费用行；`hiddenIncluded` 只以条款摘要表达，`hiddenExcluded` 不进入金额。
- [ ] `QuoteTemplateRegistry` 在服务端维护允许的 `template_key → template_version/Jinja template/renderer_version` 映射；客户端永远不能提交模板路径、HTML 或 renderer 版本。更新注册表只影响之后生成的 `QuoteDocument`，绝不修改任何已有 `QuoteVersion` 或 `QuoteDocument`。
- [ ] `ChromiumQuotePdfRenderer` 使用 `page.set_content(html, wait_until="networkidle")` 和 `page.pdf(format="A4", print_background=True, prefer_css_page_size=True)`；禁止外部网络资源，Logo 仅允许受控 data URL 或服务器静态资源。
- [ ] `QuoteDocumentService.create_document(record_id, template_key, idempotency_key)` 锁定 record，并由服务端读取 `current_version_id`；只有 `workflow_status=ready_to_send` 且 current version 同时满足 `lifecycle=locked`、`sendable=true`、`valid_until >= now` 才可生成。服务不得接受调用方传入版本快照、金额、费用、HTML 或 storage key。
- [ ] 单元测试默认注入 `FakeQuotePdfRenderer`；真实 Chromium smoke 单独标记 `@pytest.mark.pdf_smoke`。
- [ ] 运行单元测试和 smoke。

```bash
pytest -q tests/services/test_quote_document_renderer.py tests/services/test_quote_document_service.py
pytest -q -m pdf_smoke
```

- [ ] 提交。

```bash
git add apps/api/templates/quote_document_v1.html apps/api/services/quote_template_registry.py apps/api/services/quote_document_renderer.py apps/api/services/quote_document_service.py tests/services/test_quote_document_renderer.py tests/services/test_quote_document_service.py tests/fixtures/public_quote_snapshot.json
git commit -m "feat(pdf): render authoritative quote snapshots on server"
```

## Task 4: 新增文档生成、预览和下载 API

**Files:**

- Create: `apps/api/routes/quote_documents.py`
- Create: `apps/api/schemas/quote_documents.py`
- Create: `apps/api/services/customer_reply_service.py`
- Modify: `apps/api/main.py`
- Create: `tests/api/test_quote_documents.py`
- Create: `tests/api/test_quote_document_rbac.py`

- [ ] 先写 API 测试：生成、幂等返回、HTML 预览、PDF 下载、非 ready-to-send 409、非 current/非 locked/不可发送/过期 409、`pending_review` V1 禁止、渲染失败不推进报价、对象级权限 403。
- [ ] 写生成输入篡改测试：未知 `template_key` 返回 `422`；body 中出现 HTML、snapshot、version/version_no、amount、fees、renderer、template_version、file name 或 storage key 任一字段均因 `extra="forbid"` 返回 `422`，且没有文档/文件副作用。
- [ ] 写客户回复测试：回复文本只从服务端读取的 current locked sendable version 公开快照生成；读取回复和前端复制均不创建 `QuoteSendEvent`、不推进状态。
- [ ] 测试响应的 `Content-Disposition` 文件名经过清理，不能注入 header。
- [ ] 运行并确认路由不存在而失败。

```bash
pytest -q tests/api/test_quote_documents.py tests/api/test_quote_document_rbac.py
```

- [ ] API：
  - `POST /quotes/sales-records/{record_id}/documents`
  - `GET /quotes/documents/{document_id}/preview`
  - `GET /quotes/documents/{document_id}/download`
  - `GET /quotes/sales-records/{record_id}/customer-reply`
- [ ] 生成请求使用严格模型：

```python
class CreateQuoteDocumentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    template_key: str | None = None
```

- [ ] `template_key` 为空时由服务端注册表选择明确默认 key，非空时必须命中同一注册表；幂等键只从 `Idempotency-Key` header 读取。服务端自行读取 current version 及其公开快照，并决定模板/renderer 版本、客户、金额、费用、文件名和 storage key。
- [ ] preview 返回持久化 HTML，设置严格 CSP：`default-src 'none'; img-src data: 'self'; style-src 'unsafe-inline'; frame-ancestors 'self'`。
- [ ] download 流式读取存储文件，下载前检查销售所有权或后台读取权限。
- [ ] `/customer-reply` 返回依据 current version 公开快照形成的可复制客户回复文本，不从页面表单临时状态或旧 PDF 读取；预览、下载、读取回复和浏览器复制都不写成功发送事件，不改变报价状态。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/routes/quote_documents.py apps/api/schemas/quote_documents.py apps/api/services/customer_reply_service.py apps/api/main.py tests/api/test_quote_documents.py tests/api/test_quote_document_rbac.py
git commit -m "feat(api): generate preview and download quote PDFs"
```

## Task 5: 新增发送事件、跟进任务和安全发送服务

**Files:**

- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0029_quote_delivery.py`
- Create: `apps/api/db/repositories/quote_send_event_repository.py`
- Create: `apps/api/db/repositories/quote_follow_up_repository.py`
- Create: `apps/api/services/quote_send_service.py`
- Create: `apps/api/services/quote_send_reconciliation_service.py`
- Modify: `packages/email_notifier/client.py`
- Create: `tests/services/test_quote_send_service.py`
- Create: `tests/services/test_quote_send_reconciliation_service.py`
- Modify: `tests/api/test_email_notifications.py`
- Create: `tests/migrations/test_0029_quote_delivery.py`

- [ ] 先写发送服务测试：
  - 每次尝试追加独立事件；
  - 成功事件绑定当前版本和 PDF；
  - 失败保持 `ready_to_send` 且不创建跟进；
  - 成功才进入 `sent` 并创建跟进；
  - 相同幂等键不重复调用渠道；
  - 旧版本、旧 PDF、过期报价、哈希不一致阻断；
  - 第二次成功发送保留第一次事件；
  - provider 支持原生幂等时收到稳定 provider idempotency key；SMTP 始终收到稳定 `Message-ID`；
  - provider 已返回但数据库确认前进程崩溃时事件仍为 `pending`，lease 到期后的 reconciliation 才把不可查询结果改为 `unknown`，不盲目自动重发；
  - 相同幂等键在 `pending|succeeded|failed|unknown` 任一状态重试都返回原事件，永不再次调用 provider；
  - 新一次不同幂等键成功发送时复用并重排该 record 的唯一开放跟进，更新其 send event，不叠加第二条开放任务。
- [ ] 运行并确认模型/服务不存在而失败。

```bash
pytest -q tests/services/test_quote_send_service.py tests/services/test_quote_send_reconciliation_service.py tests/api/test_email_notifications.py tests/migrations/test_0029_quote_delivery.py
```

- [ ] 新增 `QuoteSendEvent`，字段包含 record/version/document、channel、mode、recipient_json、request_sha256、message_sha256、status `pending|succeeded|failed|unknown`、lease_token、lease_expires_at、provider_idempotency_key、stable_message_id、provider_message_id、idempotency_key、actor、requested/invoked/completed/reconciled 时间和错误；`(record_id, idempotency_key)` 唯一。
- [ ] 新增 `QuoteFollowUpTask`，字段包含 record、当前 send_event、owner、due_at、status `open|done|cancelled`、completed_at；使用 PostgreSQL partial unique index 保证每个 `record_id` 最多一条 `status=open` 的任务。新的成功发送重绑并重排该任务，而不是创建堆叠任务。
- [ ] 创建新迁移 `0029_quote_delivery.py`，`down_revision = "0028_quote_documents"`；禁止修改已应用迁移。迁移建立 send event、follow-up、唯一幂等约束、开放跟进 partial unique index及 reconciliation 查询索引。
- [ ] 发送渠道契约支持 provider 原生幂等键和状态查询能力标记；有能力时传稳定 `provider_idempotency_key`。`SmtpEmailClient.send` 支持 PDF 附件和服务端生成的稳定 `Message-ID`；SMTP 的 Message-ID 只降低重复风险，不宣称 exactly-once。错误日志只记录错误类型，不记录完整收件人或附件。
- [ ] 在线发送顺序：
  1. 事务 A 校验 current version/document/哈希和幂等请求哈希；首次请求写 `pending` outbox、稳定 provider key/Message-ID 和短 lease 后提交；已有同 key 请求只返回原事件，请求哈希不同则 `409`；
  2. 持 lease 的 dispatcher 调用一次 provider，并尽力记录 provider receipt；
  3. 事务 B 锁 event/record，成功则标记 `succeeded`、状态变 `sent`、创建或重排唯一开放跟进和时间线，明确失败则标记 `failed`；
  4. 如果调用后在事务 B 前崩溃，记录保持 `pending`。lease 到期后 reconciliation：支持查询的 provider 按查询结果确认；SMTP 等不可查询渠道改为 `unknown`。任何 reconciliation 都不得再次调用发送方法；
  5. `unknown` 只能由 admin 对账为 delivered/failed，记录原因、证据和 audit event；若要实际重发，必须由销售显式创建新的幂等键和新 send event。
- [ ] 线下登记不调用 SMTP，销售明确填写渠道、收件人和实际时间后直接创建 `succeeded` 事件。
- [ ] 收件人永不写回 `Customer`。
- [ ] 在临时 PostgreSQL 验证 `0028 → 0029 → 0028 → 0029`，确认降级只移除 delivery 结构且 QuoteDocument 保留；`alembic heads` 预期唯一 head 为 `0029_quote_delivery`。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/db/models.py migrations/versions/0029_quote_delivery.py apps/api/db/repositories/quote_send_event_repository.py apps/api/db/repositories/quote_follow_up_repository.py apps/api/services/quote_send_service.py apps/api/services/quote_send_reconciliation_service.py packages/email_notifier/client.py tests/services/test_quote_send_service.py tests/services/test_quote_send_reconciliation_service.py tests/api/test_email_notifications.py tests/migrations/test_0029_quote_delivery.py
git commit -m "feat(delivery): persist auditable quote send attempts"
```

## Task 6: 新增发送 API 和客户结果状态转换

**Files:**

- Modify: `apps/api/schemas/quote_lifecycle.py`
- Modify: `apps/api/schemas/admin_quote_records.py`
- Modify: `apps/api/routes/sales_records.py`
- Modify: `apps/api/routes/admin_quotes.py`
- Create: `apps/api/routes/quote_delivery_admin.py`
- Modify: `apps/api/services/quote_workflow_service.py`
- Modify: `apps/api/services/quote_application_service.py`
- Modify: `apps/api/services/quote_version_service.py`
- Modify: `apps/api/services/quote_read_service.py`
- Create: `tests/api/test_quote_send_events.py`
- Create: `tests/api/test_quote_customer_outcomes.py`
- Create: `tests/api/test_quote_followups.py`
- Create: `tests/api/test_quote_delivery_reconciliation.py`
- Create: `tests/api/test_quote_change_drafts.py`
- Create: `tests/api/test_admin_quote_delivery_detail.py`
- Create: `tests/services/test_quote_customer_outcome_service.py`

- [ ] 先写 API 测试：在线邮件发送、线下登记、多次发送、失败、pending lease 到期、unknown、无成功发送时拒绝客户结果、接受、变更、拒绝和重复幂等；相同发送幂等键的每次 API 重试都断言 provider 调用次数仍为 1。
- [ ] 写 admin 对账测试：只有 admin 可把已到期 pending/unknown 对账为 delivered 或 failed；reason 必填，写 audit；delivered 恰好执行一次 sent 状态/跟进副作用，重复相同对账幂等，矛盾对账 `409`，对账过程不调用发送 provider。
- [ ] 写 follow-up 测试：按 owner 过滤、分页、`due_at ASC, id ASC` 稳定排序和对象级权限；连续两次成功发送同一 record 后仍最多一条开放任务，并且 due_at/send_event 已重排重绑。
- [ ] 写变更测试：客户要求调整保留原 current version/PDF/send event，创建 parent 指向该已发送版本的下一 working draft，创建时不切换 `current_version_id`；销售 PATCH 草稿时旧发送版本仍 current。
- [ ] 写提交草稿测试：加拿大末端和 FCL 都必须重新调用各自服务端验证/报价引擎。自动报价成功时锁定 working version、切换 current、`sendable=true`、进入 `ready_to_send`；信息有效但需人工处理时锁定为新的 non-sendable attempt、切换 current、进入 `pending_review` 并创建复核任务；字段校验失败则 `422` 且保留可编辑草稿。
- [ ] 写 V3/V4 测试：已发送 V2 的客户改单产生 working V3；提交后 V3 成为 locked/non-sendable 的 pending-review attempt；运营复核创建 locked/sendable V4 后才允许生成 PDF 和发送，V2 文档和 send event 始终可审计。
- [ ] 写 outcome union 测试：accepted 接受 `external_order_reference` 和 `note`；change_requested 要求非空 `change_request_text`；rejected 要求枚举 `reason` 并接受 `note`；change_requested/rejected 提交订单号返回 `422`，所有类型都禁止旧名 `external_reference` 和额外自由字段。
- [ ] 写后台闭环测试：同一 record 有 V1–V4、多份 QuoteDocument、多次 send event 和多个 outcome/audit event 时，`GET /admin/quotes` 仍只返回一行并给出准确的 `version_count/document_count/send_count/outcome_count`；详情按版本嵌套真实 documents、send events、outcomes 和 follow-up 摘要，不再返回计划 3 的空占位。
- [ ] 写收件信息独立授权测试：普通 `/admin/quotes/{record_id}` 的嵌套 send event 永不包含 email/recipient_json；只有具备独立 `quotes.delivery_recipients.read` 权限的后台用户可调用收件详情端点，无该权限的 admin/operator/viewer 都返回 `403`，销售端点始终不可读取。
- [ ] 运行并确认 PR #3 的简单 `mark-sent/outcome` 无版本/文档/发送绑定而失败。

```bash
pytest -q tests/api/test_quote_send_events.py tests/api/test_quote_customer_outcomes.py tests/api/test_quote_followups.py tests/api/test_quote_delivery_reconciliation.py tests/api/test_quote_change_drafts.py tests/api/test_admin_quote_delivery_detail.py tests/services/test_quote_customer_outcome_service.py
```

- [ ] API：
  - `POST /quotes/sales-records/{record_id}/send-events`
  - `GET /quotes/sales-records/{record_id}/send-events`
  - `POST /quotes/sales-records/{record_id}/customer-outcomes`
  - `GET /quotes/sales-records/{record_id}/working-version`
  - `PATCH /quotes/sales-records/{record_id}/working-version`，请求体按 `quote_type` 判别且带 `expected_revision`
  - `POST /quotes/sales-records/{record_id}/working-version/submit`
  - `GET /quotes/follow-ups?owner_user_id=me&status=open&page=1&page_size=50`
  - `POST /quotes/follow-ups/{follow_up_id}/complete`
  - `POST /admin/quote-send-events/{send_event_id}/reconcile`
  - `GET /admin/quotes/{record_id}/delivery-recipients`（独立 `quotes.delivery_recipients.read` 权限）
- [ ] `CreateSendEventRequest` 使用 discriminated union：`online_email` 需要 email 和 document；`offline_record` 需要 channel、recipient、sent_at 和 document/version。
- [ ] 客户结果请求使用 `outcome_type` 判别联合并统一 `extra="forbid"`：

```python
class CustomerOutcomeBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

class AcceptedOutcome(CustomerOutcomeBase):
    outcome_type: Literal["accepted"]
    external_order_reference: str | None = None
    note: str | None = None

class ChangeRequestedOutcome(CustomerOutcomeBase):
    outcome_type: Literal["change_requested"]
    change_request_text: str = Field(min_length=1, max_length=2000)

class RejectedOutcome(CustomerOutcomeBase):
    outcome_type: Literal["rejected"]
    reason: Literal["price", "lead_time", "scope", "customer_cancelled", "competitor", "incomplete_information", "other"]
    note: str | None = None
```

- [ ] 客户结果写入类型化 `QuoteWorkflowEvent`，设置 `quote_version_id`、`quote_send_event_id`、`outcome_type`、对应的 note/change request/reason、仅 accepted 可用的 `external_order_reference` 和幂等键，不创建无法关联版本的自由文本结果；数据库、API 和指标全程使用同一个 `external_order_reference` 名称。
- [ ] `accepted/rejected` 关闭开放跟进；`change_requested` 关闭当前跟进、创建下一 working draft 并进入 `change_requested`，但在草稿提交成功前不切换 current；`暂无回复` 只通过 follow-up 完成/重排 API 更新 due date，不作为终态 outcome。
- [ ] working draft PATCH 只保存按 quote type 允许的结构化字段，不接受快照、金额或 sendability；submit 必须重新运行加拿大末端或 FCL 的服务端确定性引擎，不能复用页面预览金额。提交后 valid automatic 结果锁定并成为 current/sendable；manual-required 结果锁定并成为 current/non-sendable，进入复核，后续 V4 由既有复核服务创建。
- [ ] follow-up 列表默认只返回当前用户拥有的任务，后台角色可显式过滤 owner；使用 `page/page_size`，固定 `due_at ASC, id ASC`，响应返回 total。新的成功发送通过锁 record 和开放任务行来 reschedule/rebind，不创建第二条开放任务。
- [ ] admin reconcile 请求只允许 `result=delivered|failed`、必填 `reason` 和可选 evidence/provider id；delivered 复用发送成功 finalizer，failed 不推进记录。两者写 actor、时间和前后状态审计，绝不调用 provider send。
- [ ] 扩展计划 3 已有的 `admin_quote_records.py`、`admin_quotes.py` 和 `quote_read_service.py`：后台列表用 correlated aggregate/subquery 计算四类 count，不能 join 展开为多行；详情 DTO 按版本嵌套类型化 document/send/outcome/follow-up 摘要并保持公开、内部、交付、审计分区。基础详情中的收件人始终省略或脱敏，原始 `recipient_json` 只能从独立授权端点按 send event 返回并写读取审计。
- [ ] 本计划不新增通用“取消报价/手工过期”状态接口：这些状态转换仍由复核与版本计划统一定义。此处只在 PDF/发送入口强制 `valid_until`，并在 accepted/rejected 时关闭 delivery follow-up，避免出现第二套 cancel/expire 语义。
- [ ] 替换 PR #3 的旧 `mark-sent` 和无发送绑定 `outcome`：返回 `410 Gone` 或保留 deprecated adapter 但强制转入新服务，正式前端不得调用旧接口。
- [ ] 运行测试，预期通过。
- [ ] 提交。

```bash
git add apps/api/schemas/quote_lifecycle.py apps/api/schemas/admin_quote_records.py apps/api/routes/sales_records.py apps/api/routes/admin_quotes.py apps/api/routes/quote_delivery_admin.py apps/api/services/quote_workflow_service.py apps/api/services/quote_application_service.py apps/api/services/quote_version_service.py apps/api/services/quote_read_service.py tests/api/test_quote_send_events.py tests/api/test_quote_customer_outcomes.py tests/api/test_quote_followups.py tests/api/test_quote_delivery_reconciliation.py tests/api/test_quote_change_drafts.py tests/api/test_admin_quote_delivery_detail.py tests/services/test_quote_customer_outcome_service.py
git commit -m "feat(delivery): close send and customer outcome workflow"
```

## Task 7: 建立销售 PDF、发送和客户结果界面

**Files:**

- Remove from active path: `apps/web/src/components/fclQuoteHtml.ts`
- Create: `apps/web/src/features/documents/QuoteDocumentPanel.tsx`
- Create: `apps/web/src/features/documents/QuoteDocumentPreview.tsx`
- Create: `apps/web/src/features/documents/CustomerReplyCopyButton.tsx`
- Create: `apps/web/src/features/delivery/QuoteSendDialog.tsx`
- Create: `apps/web/src/features/delivery/SendHistory.tsx`
- Create: `apps/web/src/features/delivery/CustomerOutcomePanel.tsx`
- Create: `apps/web/src/features/delivery/FollowUpCard.tsx`
- Create: `apps/web/src/features/delivery/QuoteDeliveryFlow.test.tsx`
- Modify: `apps/web/src/pages/sales/QuoteRecordDetailPage.tsx`
- Modify: `apps/web/src/pages/sales/SalesFollowUpsPage.tsx`
- Modify: `apps/web/src/pages/QuotePage.tsx`
- Modify: `apps/web/src/features/fcl/FclQuoteForm.tsx`
- Modify: `apps/web/src/pages/admin/AdminQuoteRecordsPage.tsx`
- Modify: `apps/web/src/pages/admin/AdminQuoteDetailPage.tsx`
- Modify: `apps/web/src/features/admin-quotes/AdminQuoteTable.tsx`
- Modify: `apps/web/src/features/admin-quotes/NestedVersionSendHistory.tsx`
- Create: `apps/web/src/features/admin-quotes/DeliveryRecipientDetails.tsx`
- Modify: `apps/web/src/pages/admin/AdminQuoteDetailPage.test.tsx`
- Modify: `apps/web/src/api/quoteDocuments.ts`
- Modify: `apps/web/src/api/quoteDelivery.ts`
- Modify: `apps/web/src/api/adminQuotes.ts`
- Modify: `apps/web/src/domain/quoteWorkflow.ts`
- Modify: `apps/web/src/domain/adminQuotes.ts`

- [ ] 先写组件闭环测试：锁定当前版本 → 生成 PDF → 预览/下载不改状态 → 成功发送 → 显示发送历史和跟进 → 客户接受/变更/拒绝。
- [ ] 写异常测试：PDF 失败、发送失败、过期、旧版本、409 revision 冲突；按钮文案和状态不虚假前进。
- [ ] 写客户字段测试：发送对话框有本次收件人，客户档案页面仍只有名称。
- [ ] 写客户回复复制测试：按钮文本由 `/customer-reply` 的 current version snapshot 响应提供，复制后只显示“已复制”，网络层没有 send-event 请求，报价状态和发送历史不变。
- [ ] 写改单表单测试：从 V2 的 change_requested 打开加拿大末端或 FCL 表单时加载服务端 working draft；保存只 PATCH 草稿且不替换 current；submit 以后按响应进入 V3 ready-to-send 或 V3 pending-review，不能用本地预览假定成功。
- [ ] 写后台详情测试：列表仍一报价一行并显示 version/document/send/outcome counts；详情用真实嵌套数据替换空占位，按版本展示文档、发送、结果和跟进。基础详情不含原始收件人，只有拥有独立授权且用户主动展开时才请求收件详情。
- [ ] 写移动端测试：主要动作在底部固定栏，预览全屏，发送/结果对话框可键盘操作。
- [ ] 运行并确认当前 `fclQuoteHtml` 前端打印路径无法通过。

```bash
cd apps/web
npm test -- --run src/features/delivery/QuoteDeliveryFlow.test.tsx
```

- [ ] `QuoteDocumentPreview` iframe 只加载服务器 preview URL，设置 `sandbox="allow-same-origin"`，不允许脚本。
- [ ] 页面明确区分“生成”“预览”“下载”“发送”；只有 send event `succeeded` 显示“已发送”。
- [ ] `CustomerReplyCopyButton` 只复制服务端从 current version 公开快照生成的文本；复制动作仅使用 Clipboard API，不调用发送接口、不写 send event，也不显示“已发送”。
- [ ] 发送对话框默认选择当前版本的最新有效文档；文档过时或不存在时先要求重新生成。
- [ ] 在线邮件和线下登记分成两个明确入口；微信/企业微信当前只允许线下登记，不伪装自动发送。
- [ ] 客户变更后按 quote type 跳转相应结构化表单；`QuotePage` 与 `FclQuoteForm` 都通过 working-version API 加载/保存同一服务端草稿，顶部保留“来源 Vn / 已发送于 …”。提交结果为 pending-review 时立即只读显示 V3 和“等待复核”，运营生成 V4 后销售才恢复生成/发送动作。
- [ ] `AdminQuoteRecordsPage` 和 `AdminQuoteTable` 只消费 record 级摘要及 count，不把 nested arrays 展成重复报价行；`AdminQuoteDetailPage`/`NestedVersionSendHistory` 展示正式 QuoteDocument、SendEvent、Outcome 和 follow-up 数据。`DeliveryRecipientDetails` 延迟调用独立端点，无权限时不请求、不猜测、不从其他 DTO 拼出收件人，并记录授权错误而不破坏其余详情。
- [ ] 旧 `fclQuoteHtml.ts` 不再被正式路径 import；若仍保留兼容测试，标记 deprecated 并禁止发送调用。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/components/fclQuoteHtml.ts apps/web/src/features/documents apps/web/src/features/delivery apps/web/src/pages/sales/QuoteRecordDetailPage.tsx apps/web/src/pages/sales/SalesFollowUpsPage.tsx apps/web/src/pages/QuotePage.tsx apps/web/src/features/fcl/FclQuoteForm.tsx apps/web/src/pages/admin/AdminQuoteRecordsPage.tsx apps/web/src/pages/admin/AdminQuoteDetailPage.tsx apps/web/src/features/admin-quotes/AdminQuoteTable.tsx apps/web/src/features/admin-quotes/NestedVersionSendHistory.tsx apps/web/src/features/admin-quotes/DeliveryRecipientDetails.tsx apps/web/src/pages/admin/AdminQuoteDetailPage.test.tsx apps/web/src/api/quoteDocuments.ts apps/web/src/api/quoteDelivery.ts apps/web/src/api/adminQuotes.ts apps/web/src/domain/quoteWorkflow.ts apps/web/src/domain/adminQuotes.ts
git commit -m "feat(web): add version-bound PDF send and outcome flow"
```

## Task 8: 添加浏览器闭环验收

**Files:**

- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Create: `apps/web/playwright.config.ts`
- Create: `apps/web/e2e/automatic-final-mile-loop.spec.ts`
- Create: `apps/web/e2e/fcl-review-loop.spec.ts`
- Create: `apps/web/e2e/send-failure-and-change.spec.ts`
- Create: `apps/web/e2e/accessibility-and-responsive.spec.ts`
- Create: `tests/e2e/seed_quote_workflows.py`

- [ ] 安装 Playwright Test 并增加 `e2e` 脚本。

```bash
cd apps/web
npm install --save-dev @playwright/test @axe-core/playwright
npx playwright install chromium
```

- [ ] 自动末端场景断言正确货物计算、锁定 V1、生成 PDF、成功线下登记和接受。
- [ ] FCL 场景断言无原始解析入口、提交 V1、运营补资料、复核 Vn、销售只能发送新版本。
- [ ] 失败/改单场景断言 PDF 失败和发送失败都不推进；客户变更保留已发送 V2 文档，创建但不切 current 的 working V3；V3 submit 进入 locked/non-sendable pending review，运营形成 locked/sendable V4 后才可生成新 PDF/发送。
- [ ] 浏览器断言“复制客户回复”内容来自 current version，复制前后 send event 数量完全不变；后台报价列表始终一 record 一行，详情的 V2/V3/V4 下能看到各自文档、发送和结果。
- [ ] 在 1440×900 和 390×844 两个视口验收销售、复核、配置、管理数据四类核心页面：无横向溢出、主动作可见、表格与移动卡字段一致。
- [ ] 使用 `@axe-core/playwright` 扫描核心页面，`serious` 和 `critical` 违规为 0；图表同时有可读标题、图例和数据表入口。
- [ ] 每个测试使用独立幂等键和数据库种子，结束后只清理自身测试记录。
- [ ] 运行三条 e2e；修复直到通过。

```bash
npm run e2e
```

- [ ] 提交。

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/playwright.config.ts apps/web/e2e tests/e2e/seed_quote_workflows.py
git commit -m "test(e2e): cover quote document and customer loops"
```

## Task 9: 最终安全和回归门槛

- [ ] PDF/发送/结果定向测试：

```bash
pytest -q tests/services/test_quote_document_renderer.py tests/services/test_quote_document_service.py tests/storage/test_quote_document_storage.py tests/db/test_quote_document_repository.py tests/migrations/test_0028_quote_documents.py tests/api/test_quote_documents.py tests/api/test_quote_document_rbac.py tests/services/test_quote_send_service.py tests/services/test_quote_send_reconciliation_service.py tests/migrations/test_0029_quote_delivery.py tests/api/test_quote_send_events.py tests/api/test_quote_customer_outcomes.py tests/api/test_quote_followups.py tests/api/test_quote_delivery_reconciliation.py tests/api/test_quote_change_drafts.py tests/api/test_admin_quote_delivery_detail.py tests/services/test_quote_customer_outcome_service.py
```

- [ ] 全量后端：

```bash
pytest -q tests
```

- [ ] 真实 Chromium smoke：

```bash
pytest -q -m pdf_smoke
```

- [ ] 前端全部测试、构建和 e2e：

```bash
cd apps/web
npm test -- --run
npm run build
npm run e2e
```

- [ ] PostgreSQL 迁移：

```bash
cd ../..
alembic heads
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic upgrade head
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic downgrade 0028_quote_documents
DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:55432/ai_quote_test alembic upgrade 0029_quote_delivery
```

- [ ] 上述最终门槛只验证本计划最后一步 `0029 → 0028 → 0029`；Task 2 已单独验证 `0028 → 0027 → 0028`，整条 `0022 → 0029 → 0022 → 0029` 仅在总计划中执行，避免各子计划重复承担完整链。

- [ ] 对销售 API JSON、持久化 HTML、PDF 提取文本执行禁止字段扫描，以下词命中为 0：`vendor`、`cost_unit_price`、`source`、`priority`、`rate_card_id`、`internal_note`、内部汇率源。
- [ ] 搜索所有正式路由，确认页面不再 import `styles/legacy.css` 或使用旧命名空间；迁移全部仍可访问页面后删除 `legacy.css`。若某个诊断工具尚未迁移，只能保留为 `/admin/tools/*` 下显式标注的 scoped `tools-legacy.css`，不得污染销售或后台核心页面。
- [ ] 重跑 1440×900、390×844 响应式验收和 axe 扫描，确认旧样式清理没有回归。
- [ ] 验证一个版本的 `snapshot_sha256`、QuoteDocument `version_snapshot_sha256` 和生成时哈希一致；PDF 文件 SHA 与数据库一致。
- [ ] 验证下载/预览不创建 send event，失败 send 不创建 follow-up，成功 send 恰好创建一个 follow-up。
- [ ] `git diff --check` 和 `git status --short`。
- [ ] 更新 Draft PR，附完整测试、迁移、浏览器验收和残余风险；保持 Draft，不合并、不部署。
