# AI Quote Foundation and Separate Shells Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立可测试的前端基础、彻底分开的销售与后台应用壳、统一视觉组件，以及只保存名称的客户档案。

**Architecture:** `main.tsx` 仅按 URL 前缀分发到 `SalesApp` 或 `AdminApp`；两者拥有不同路由、认证守卫和导航。共享组件只包含无业务权限的视觉基础。客户目录由 FastAPI 和 SQLAlchemy 持久化，本阶段让报价通过 `customer_id` 关联客户；不可变报价版本中的客户名称快照由计划 3 冻结，不能用客户目录当前名称替代历史快照。

**Tech Stack:** React 18、TypeScript、Vite、Vitest、Testing Library、FastAPI、Pydantic、SQLAlchemy、Alembic、Pytest。

---

## Task 1: 建立前端测试基线

**Files:**

- Modify: `apps/web/package.json`
- Modify: `apps/web/package-lock.json`
- Modify: `apps/web/vite.config.ts`
- Create: `apps/web/src/test/setup.ts`
- Create: `apps/web/src/test/render.tsx`
- Create: `apps/web/src/test/server.ts`
- Create: `apps/web/src/routing/path.test.ts`
- Create: `apps/web/src/routing/path.ts`

- [ ] 安装路由和测试依赖并增加 `test`、`test:watch` 脚本。

```bash
cd apps/web
npm install react-router-dom
npm install --save-dev vitest jsdom @testing-library/react @testing-library/user-event @testing-library/jest-dom msw
```

`package.json` 脚本固定为：

```json
{
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build",
    "preview": "vite preview",
    "test": "vitest",
    "test:watch": "vitest"
  }
}
```

- [ ] 先写 `path.test.ts`，覆盖 `/quote`、`/quote/customers`、`/admin`、`/admin/reviews`、未知路径和 `VITE_APP_BASE_PATH`。
- [ ] 运行测试并确认因 `path.ts` 不存在或导出缺失而失败。

```bash
npm test -- --run src/routing/path.test.ts
```

- [ ] 实现 `normalizeBasePath`、`stripBasePath`、`classifyAppSurface` 和 `navigateTo`，不把销售路由加入后台路由联合类型。
- [ ] 在 `vite.config.ts` 增加 `test.environment="jsdom"`、`setupFiles=["./src/test/setup.ts"]` 和 `css=true`。
- [ ] `setup.ts` 导入 `@testing-library/jest-dom/vitest`，每次测试清理 DOM 和本地认证存储；`server.ts` 提供可按测试覆盖的 MSW 服务端，未声明请求默认报错，禁止测试意外访问真实 API。
- [ ] 再次运行定向测试，预期通过。
- [ ] 运行 `npm run build`，预期 TypeScript 和 Vite 构建通过。
- [ ] 提交。

```bash
git add apps/web/package.json apps/web/package-lock.json apps/web/vite.config.ts apps/web/src/test apps/web/src/routing
git commit -m "test(web): add application shell test harness"
```

## Task 2: 拆分销售和后台应用壳

**Files:**

- Modify: `apps/web/src/main.tsx`
- Replace: `apps/web/src/App.tsx`
- Create: `apps/web/src/app/RootApp.tsx`
- Create: `apps/web/src/app/NotFoundPage.tsx`
- Create: `apps/web/src/apps/SalesApp.tsx`
- Create: `apps/web/src/apps/AdminApp.tsx`
- Create: `apps/web/src/layouts/SalesShell.tsx`
- Create: `apps/web/src/layouts/AdminShell.tsx`
- Create: `apps/web/src/auth/AuthGate.tsx`
- Create: `apps/web/src/apps/SalesApp.test.tsx`
- Create: `apps/web/src/apps/AdminApp.test.tsx`
- Modify: `apps/web/src/api/client.ts`

- [ ] 先写销售壳测试：访问 `/quote` 只出现“工作台 / 客户与报价 / 待办跟进”，不出现“规则与价格 / 用户与权限 / 运营工作台”。
- [ ] 先写后台壳测试：访问 `/admin` 只出现后台六个一级入口，不出现销售一级导航或“新建报价”主按钮。
- [ ] 写角色测试：`sales` 访问 `/admin` 显示 403 友好页；`viewer` 访问配置写页面只读；`admin` 可进入后台且可单独打开销售前台。
- [ ] 运行测试并确认当前单体 `App.tsx` 结构导致失败。

```bash
cd apps/web
npm test -- --run src/apps/SalesApp.test.tsx src/apps/AdminApp.test.tsx
```

- [ ] 将现有 `App.tsx` 缩减为兼容导出；`main.tsx` 只挂载 `BrowserRouter basename={APP_BASE_PATH}` 和 `RootApp`。`RootApp` 用两个 lazy route tree 分发 `/quote/*` 与 `/admin/*`，而不是继续扩展手写 `popstate` 路由。
- [ ] `SalesApp` 不导入任何后台页面，`AdminApp` 不导入任何销售页面；构建时仅共享认证基础、无业务权限的 UI 组件和领域类型。
- [ ] `SalesApp` 定义独立路由：
  - `/quote`
  - `/quote/new/final-mile`
  - `/quote/new/fcl`
  - `/quote/customers`
  - `/quote/records`
  - `/quote/records/:recordId`
  - `/quote/follow-ups`
- [ ] `AdminApp` 定义独立路由：
  - `/admin`
  - `/admin/reviews`
  - `/admin/reviews/:taskId`
  - `/admin/quotes`
  - `/admin/quotes/:recordId`
  - `/admin/pricing`
  - `/admin/management`
  - `/admin/users`
  - 现有 AI 调试、Hermes 和批量诊断降级到 `/admin/tools/*` 二级工具路由；审计挂入报价记录，AI/搜索/通知设置挂入规则与价格的高级设置。
- [ ] 从后台导航删除 `/quote` 和 `/ai-quote`；FCL 销售报价仅在销售前台出现。
- [ ] 把现有后台会话恢复和登录逻辑封装为 `AuthGate`，显式传入 `allowedRoles`；销售与后台各自调用，不共享导航状态。
- [ ] 未识别路由显示对应应用内的 404，不自动跳到另一个应用。
- [ ] 再次运行壳测试和构建，预期通过。
- [ ] 提交。

```bash
git add apps/web/src/main.tsx apps/web/src/App.tsx apps/web/src/app apps/web/src/apps apps/web/src/layouts apps/web/src/auth apps/web/src/api/client.ts
git commit -m "feat(web): separate sales and admin application shells"
```

## Task 3: 建立统一视觉基础组件

**Files:**

- Modify: `apps/web/src/styles.css`
- Create: `apps/web/src/styles/index.css`
- Create: `apps/web/src/styles/tokens.css`
- Create: `apps/web/src/styles/base.css`
- Create: `apps/web/src/styles/accessibility.css`
- Create: `apps/web/src/styles/sales.css`
- Create: `apps/web/src/styles/admin.css`
- Create: `apps/web/src/styles/legacy.css`
- Create: `apps/web/src/components/ui/PageHeader.tsx`
- Create: `apps/web/src/components/ui/StatusBadge.tsx`
- Create: `apps/web/src/components/ui/NextActionCard.tsx`
- Create: `apps/web/src/components/ui/MetricCard.tsx`
- Create: `apps/web/src/components/ui/DataTable.tsx`
- Create: `apps/web/src/components/ui/RecordCard.tsx`
- Create: `apps/web/src/components/ui/FilterBar.tsx`
- Create: `apps/web/src/components/ui/Timeline.tsx`
- Create: `apps/web/src/components/ui/MoneyAmount.tsx`
- Create: `apps/web/src/components/ui/ResponsiveActionBar.tsx`
- Create: `apps/web/src/components/ui/ui.test.tsx`

- [ ] 先写组件测试，验证状态徽标使用可读中文文本、金额按币种格式化、表格有标题/表头、移动卡片保留同一字段、动作栏只渲染传入动作。
- [ ] 运行测试并确认组件不存在而失败。

```bash
cd apps/web
npm test -- --run src/components/ui/ui.test.tsx
```

- [ ] 把现有 `styles.css` 内容移动到临时 `legacy.css`，`styles.css` 只导入 `styles/index.css`；新代码不得继续向 7,000 行级旧样式追加覆盖。
- [ ] 在 `tokens.css` 固定浅冷灰背景、专业蓝主色、低饱和状态色、间距、圆角、边框、阴影、字号和焦点环；禁止在新页面散落新的十六进制颜色。
- [ ] 统一断点为 640、768、1024、1280、1536px；迁移页面时删除旧的 470、760、767、900、1050、1100、1179、1180、1440、1500px 断点，不长期保留两套响应式规则。
- [ ] `MoneyAmount` 接受字符串金额和 ISO 币种，不用浮点数重新计算，只做 `Intl.NumberFormat` 显示。
- [ ] `DataTable` 在 `max-width: 768px` 切换 `RecordCard`；两者使用同一行数据映射，关键状态和金额不依赖横向滚动。
- [ ] 所有交互控件满足键盘焦点、可见 label、`aria-live` 和最小 44px 移动触控高度。
- [ ] 运行测试、构建和 `git diff --check`。
- [ ] 提交。

```bash
git add apps/web/src/styles.css apps/web/src/styles apps/web/src/components/ui
git commit -m "feat(web): add shared quote workbench design system"
```

## Task 4: 拆分 API 客户端和领域类型

**Files:**

- Refactor: `apps/web/src/api/client.ts`
- Create: `apps/web/src/api/http.ts`
- Create: `apps/web/src/api/auth.ts`
- Create: `apps/web/src/api/customers.ts`
- Create: `apps/web/src/api/salesQuotes.ts`
- Create: `apps/web/src/api/adminQuotes.ts`
- Create: `apps/web/src/api/reviews.ts`
- Create: `apps/web/src/api/quoteDocuments.ts`
- Create: `apps/web/src/api/quoteDelivery.ts`
- Create: `apps/web/src/api/pricing.ts`
- Create: `apps/web/src/api/management.ts`
- Create: `apps/web/src/api/systemSettings.ts`
- Create: `apps/web/src/domain/auth.ts`
- Create: `apps/web/src/domain/customers.ts`
- Create: `apps/web/src/domain/quotes.ts`
- Create: `apps/web/src/domain/adminQuotes.ts`
- Create: `apps/web/src/domain/quoteWorkflow.ts`
- Create: `apps/web/src/api/http.test.ts`

- [ ] 先写 HTTP 层测试：按销售/后台作用域读取正确凭据、统一解析错误、`401` 清理对应会话、`409` 保留结构化冲突、请求取消不显示业务错误。
- [ ] 运行测试并确认旧单体 `client.ts` 无法独立测试这些边界。

```bash
cd apps/web
npm test -- --run src/api/http.test.ts
```

- [ ] `http.ts` 只负责 base URL、header、JSON/文件响应和类型化错误；不包含任何报价业务类型。
- [ ] `domain/*` 只定义服务端 DTO 对应类型；`QuoteWorkflowStatus` 与后端枚举逐项一致。
- [ ] 按业务域移动 API 方法；销售报价使用 `salesQuotes.ts`，后台报价记录/详情使用独立 `adminQuotes.ts` 和 `domain/adminQuotes.ts`，复核任务使用 `reviews.ts`，禁止把后台报价读取塞回销售模块。`client.ts` 暂时只作为兼容 barrel export，禁止继续新增实现。
- [ ] 后续计划把页面 import 逐步迁到新模块；计划 5 完成后删除无调用的旧 export。
- [ ] 运行测试和构建，提交。

```bash
git add apps/web/src/api apps/web/src/domain
git commit -m "refactor(web): split API client and quote domain types"
```

## Task 5: 新增仅名称客户模型和迁移

**Files:**

- Modify: `apps/api/db/models.py`
- Create: `migrations/versions/0023_customers.py`
- Create: `apps/api/db/repositories/customer_repository.py`
- Create: `tests/db/test_customer_repository.py`
- Create: `tests/db/test_quote_lifecycle_constraints.py`
- Create: `tests/migrations/test_0023_customers.py`

- [ ] 先写仓储测试：创建客户只接受名称；名称去除首尾空格；规范化名称用于重名提示但允许同名；列表按当前用户可见报价的最近使用时间和名称搜索；销售只能看到自己创建的客户，或至少被一条自己拥有的报价关联的客户；销售只能改自己创建的客户；运营/管理员按其授权后台范围读取，管理员可改任意客户。
- [ ] 先写约束测试：`SalesQuoteRecord.customer_id` 可以为空以兼容历史数据；关联客户后删除客户必须受限而不是级联删除历史报价。
- [ ] 先写迁移测试：`0023_customers` 的 `down_revision == "0022_quote_workflow"`，升级后存在 `customers`、`sales_quote_records.customer_id`、外键和索引，降级只撤销本迁移对象且不损坏 `0022_quote_workflow` 数据。
- [ ] 运行测试并确认模型和仓储不存在而失败。

```bash
pytest -q tests/db/test_customer_repository.py tests/db/test_quote_lifecycle_constraints.py tests/migrations/test_0023_customers.py
```

- [ ] 在 `models.py` 新增 `Customer`：

```python
class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    normalized_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    created_by_user_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now())
```

- [ ] 在 `0023_customers.py` 中创建 `customers`，给 `sales_quote_records` 增加可空 `customer_id` 外键和索引；固定 `revision = "0023_customers"`、`down_revision = "0022_quote_workflow"`。本迁移提交后禁止后续计划继续修改 `0023_customers.py`，任何新结构都必须创建线性的下一号迁移。
- [ ] `normalize_customer_name` 使用 Unicode NFKC、折叠连续空白和 `casefold()`；不得删除有业务意义的中文或标点。
- [ ] 仓储列表返回 `possible_duplicate`，不因同名拒绝创建；“最近使用”排序只可基于调用者有权访问的报价，绝不能通过排序、计数或时间戳侧漏其他销售的报价或活动。
- [ ] 运行定向测试，预期通过。
- [ ] 在一次性 PostgreSQL 测试库执行 `upgrade 0023_customers → downgrade 0022_quote_workflow → upgrade 0023_customers`，验证真实外键、索引、降级和再次升级；SQLite 结果不能代替此门禁。
- [ ] 运行 `alembic heads`，以精确断言确认唯一 head 为 `0023_customers`。
- [ ] 提交。

```bash
git add apps/api/db/models.py apps/api/db/repositories/customer_repository.py migrations/versions/0023_customers.py tests/db/test_customer_repository.py tests/db/test_quote_lifecycle_constraints.py tests/migrations/test_0023_customers.py
git commit -m "feat(customers): add minimal name-only customer directory"
```

## Task 6: 新增客户 API 和权限测试

**Files:**

- Create: `apps/api/routes/customers.py`
- Create: `apps/api/schemas/customers.py`
- Modify: `apps/api/main.py`
- Modify: `apps/api/auth.py`
- Create: `tests/api/test_customers.py`

- [ ] 先写 API 测试：
  - 销售只能搜索自己创建的客户，或被自己拥有的报价关联的客户；不能搜索、按最近使用推断或直接按 ID 读取其他销售独占的客户；
  - 运营和管理员只在后台授权范围内搜索名称；返回值不得携带任何销售的报价、活动、成交或跟进信息；
  - 销售和管理员可创建客户；
  - 请求只接受 `{"name": "客户名"}`，逐项验证 `email`、`phone`、`contact`、`note` 以及任意其他字段均返回 `422`；
  - 销售只能重命名自己创建的客户；
  - 运营和 viewer 只读；
  - 列表分页返回 `records/total/limit/offset`。
- [ ] 运行测试并确认 404 或 schema 缺失失败。

```bash
pytest -q tests/api/test_customers.py
```

- [ ] 用 `ConfigDict(extra="forbid", str_strip_whitespace=True)` 定义 `CustomerCreate` 和 `CustomerUpdate`，二者只有 `name`。
- [ ] 实现：
  - `GET /customers`
  - `POST /customers`
  - `PATCH /customers/{customer_id}`
- [ ] 将 `customers_router` 注册到 `apps/api/main.py`。
- [ ] 查询在仓储层强制注入当前用户作用域，不能先查全量再在 Python 过滤；销售作用域为 `created_by_user_id == current_user.id OR EXISTS(当前销售拥有且 customer_id 相同的报价)`，后台运营/管理员使用显式后台授权作用域。
- [ ] 响应不返回用户凭据、报价数量、最近报价状态、活动时间线或报价内容，只返回客户公开名称字段和 `possible_duplicate`；不存在可绕过作用域的通用 `GET /customers/{customer_id}`。
- [ ] 再次运行 API 测试和全量权限回归。

```bash
pytest -q tests/api/test_customers.py tests/api/test_api_keys_auth.py
```

- [ ] 提交。

```bash
git add apps/api/routes/customers.py apps/api/schemas/customers.py apps/api/main.py apps/api/auth.py tests/api/test_customers.py
git commit -m "feat(api): expose name-only customer directory"
```

## Task 7: 销售客户页和基础待办页

**Files:**

- Create: `apps/web/src/pages/sales/SalesWorkbenchPage.tsx`
- Create: `apps/web/src/pages/sales/CustomerDirectoryPage.tsx`
- Create: `apps/web/src/pages/sales/SalesFollowUpsPage.tsx`
- Create: `apps/web/src/pages/sales/CustomerDirectoryPage.test.tsx`
- Create: `apps/web/src/pages/sales/SalesFollowUpsPage.test.tsx`
- Create: `apps/web/src/features/customers/CustomerNameField.tsx`
- Create: `apps/web/src/features/customers/CustomerNameField.test.tsx`
- Modify: `apps/web/src/apps/SalesApp.tsx`
- Modify: `apps/web/src/api/customers.ts`
- Modify: `apps/web/src/api/salesQuotes.ts`
- Modify: `apps/web/src/domain/customers.ts`
- Modify: `apps/web/src/domain/quotes.ts`

- [ ] 先写 `CustomerNameField` 测试：只有带可见 label 的名称搜索/选择/创建；不渲染联系人、电话、邮箱、地址、备注；只向 API 发送 `name`；销售不能看到 MSW 注入的其他销售独占客户；同名提示不阻止显式确认创建。
- [ ] 先写客户页测试：创建后列表立即显示；点击客户只跳转到 `/quote/records?customer_id=<id>` 并筛选销售有权查看的报价记录，不打开独立 CRM 详情页，也不请求客户活动或其他销售报价。
- [ ] 先写待办页测试：`needs_sales_info`、`ready_to_send`、临近过期和超时 `sent` 按优先级显示；每项只有一个主要动作。
- [ ] 运行测试并确认页面或 API 客户端缺失失败。

```bash
cd apps/web
npm test -- --run src/pages/sales/CustomerDirectoryPage.test.tsx src/pages/sales/SalesFollowUpsPage.test.tsx
```

- [ ] 在 `domain/customers.ts` 增加类型化 `CustomerSummary`、`CustomerListResponse`，在 `api/customers.ts` 增加 CRUD 调用；禁止 `any`。
- [ ] 实现可复用 `CustomerNameField`，销售末端和 FCL 表单只能复用该组件选择必填 `customer_id`；组件不得接受或缓存名称之外的客户资料。
- [ ] `SalesWorkbenchPage` 首屏固定为“新建报价 → 今日待办 → 最近报价”，新建报价类型保存在用户侧偏好键 `sales:last-quote-type`，仅保存 `final_mile|fcl`。
- [ ] `SalesFollowUpsPage` 使用 PR #3 的 `workflow_status/next_action/allowed_actions/valid_until`；计划 3 完成后切换到新的摘要 DTO，不读取 `result_json`。
- [ ] 客户页提交时只发送 `name`；客户列表行的唯一业务动作是筛选报价记录，不新增客户详情/联系人/活动页。
- [ ] 运行测试和构建。
- [ ] 提交。

```bash
git add apps/web/src/pages/sales apps/web/src/features/customers apps/web/src/apps/SalesApp.tsx apps/web/src/api/customers.ts apps/web/src/api/salesQuotes.ts apps/web/src/domain/customers.ts apps/web/src/domain/quotes.ts
git commit -m "feat(web): add sales workbench customers and follow-ups"
```

## Task 8: 基础阶段回归

- [ ] 运行后端定向测试。

```bash
pytest -q tests/db/test_customer_repository.py tests/migrations/test_0023_customers.py tests/api/test_customers.py tests/api/test_api_keys_auth.py
```

- [ ] 在一次性 PostgreSQL 数据库执行迁移往返门禁，并保存输出作为阶段证据：

```bash
alembic upgrade 0023_customers
alembic downgrade 0022_quote_workflow
alembic upgrade 0023_customers
test "$(alembic heads | awk '{print $1}')" = "0023_customers"
```

- [ ] 运行前端测试和构建。

```bash
cd apps/web
npm test -- --run
npm run build
```

- [ ] 回到仓库根目录，运行：

```bash
cd ../..
alembic heads
git diff --check
git status --short
```

- [ ] 手工打开 `/quote` 和 `/admin`，确认导航、登录和 404 完全分开。
- [ ] 用销售账号访问 `/admin`，确认服务端数据请求也返回 `403`。
- [ ] 确认客户 API 和浏览器网络请求中没有联系方式字段。
- [ ] 用两名销售分别创建客户和报价，确认任何客户搜索、排序、点击筛选和网络响应都不会泄露另一名销售的报价或活动；运营/管理员仅看到其后台授权范围。
- [ ] 将验证结果记录到分支说明，继续执行计划 2；不合并、不部署。
