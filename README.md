# Canada Final Mile Auto Quote

用于加拿大尾端卡车派送自动报价的项目仓库。第一版目标是先把结构化导入、
FSA 匹配、确定性报价、AI 输出保护做稳，避免任何模型编造价格。

## 项目目标

- 根据派送地址、邮编、货物信息和服务要求自动生成尾端卡车派送报价。
- 支持区域/邮编分区、托盘数量、附加服务、燃油费、住宅派送、预约派送等费用规则。
- 预留报价 API、规则配置、报价记录和人工审核流程。

## 核心边界

- AI 不直接报价。
- AI 不读取完整 Excel 或完整报价表。
- AI 不允许编造市场价、附加费或距离费。
- 报价必须由确定性 Quote Engine 计算。
- AI 只能基于 `quote_result` 解释报价、生成销售备注、提示风险。
- 未命中价格库时返回 `manual_required`，不输出客户报价金额。

报价链路：

```text
Excel/CSV 导入
-> 数据标准化
-> PostgreSQL 结构化价格库
-> SQL/规则引擎匹配
-> 确定性计算
-> AI 解释与输出校验
```

## 工程结构

```text
apps/api/                         FastAPI 服务
apps/web/                         内部报价工作台
packages/quote_engine/            确定性报价引擎
packages/address_normalizer/       加拿大地址、邮编、FSA、省份标准化
packages/data_importer/            Excel/CSV 导入和字段校验
packages/ai_assistant/             AI 小上下文构造和输出金额校验
packages/shared/                   共享常量
data/                              原始数据、模板和脱敏样例占位
docs/                              产品、规则、数据结构和 AI 防幻觉文档
infra/                             Docker Compose 和 Postgres 初始化表
reference/canada-final-mile/       已归档的业务资料和查表数据
tests/                             MVP 单元测试
```

## MVP 功能

- 读取并校验供应商报价表标准字段。
- 标准化加拿大邮编，例如 `v6v1a1 -> V6V 1A1 -> V6V`。
- 标准化省份，例如 `Ontario -> ON`、`British Columbia -> BC`。
- 按 Zone 查表链路报价：
  `postal_code -> preferred city -> postal_prefix/city/province -> zone/origin -> zone_price_matrix`
- 按固定优先级匹配报价规则：
  `history_exact_address -> postal_code -> fsa -> city -> rate_card -> distance_fallback -> manual_required`
- 输出 `source_type`、`confidence`、`matched_rule`、`cost_breakdown`、风险标签和人工审核状态。
- AI 输出后校验金额，发现不在 `quote_result` 里的金额会拦截。
- 大模型可参与客户原始话术理解、字段提取和销售话术润色，但不能自由算价；
  `total_price_usd`、Zone、计费托数、燃油和附加费必须来自后端 Quote Engine。

## 本地开发

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
pytest
```

启动 API：

```bash
uvicorn apps.api.main:app --reload
```

启动内部报价工作台：

```bash
cd apps/web
npm install
npm run dev
```

前端默认请求 `http://localhost:8000`。如需修改 API 地址：

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

工作台页面：

- `/quote`：普通 Zone 报价输入。
- `/ai-quote`：粘贴客户原始消息，由 AI 提取字段，再由 Zone Quote Engine 报价。
- `/manual-tasks`：处理 `manual_required` 人工确认任务。
- `/audit`：按 `quote_id` 查询报价审计记录。
- `/settings/ai`：维护 OpenAI-compatible 模型配置。
- `/settings/wecom`：维护企业微信群机器人 Webhook 配置。

Docker Compose：

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

数据库迁移：

```bash
alembic upgrade head
```

开发库默认读取 `DATABASE_URL`，未设置时使用本地 Docker Compose 的 Postgres
连接。新增或调整表结构时先修改 SQLAlchemy ORM，再生成迁移草稿：

```bash
alembic revision --autogenerate -m "describe schema change"
alembic upgrade head
```

`infra/postgres/init.sql` 仍保留用于本地容器首次初始化和演示数据；后续新增表、
字段、索引必须通过 `migrations/versions/` 里的 Alembic migration 管理。测试库
使用 SQLite 内存库，并由 `Base.metadata.create_all()` 自动建表。
如果某个开发库已经由 `init.sql` 初始化到当前结构，可先执行 `alembic stamp head`
标记版本；之后再用 `alembic upgrade head` 应用新增 migration。

### API Key 权限

本地开发可在 `.env` 设置：

```bash
DEV_AUTH_DISABLED=true
```

关闭后端认证。开启认证时，请把 `DEV_AUTH_DISABLED` 设为 `false`，并在请求里传：

```bash
X-API-Key: caq_xxx
```

API Key 只在创建时返回一次明文，数据库只保存 `key_hash`。管理接口：

```bash
GET /api-keys
POST /api-keys
PATCH /api-keys/{key_id}
```

角色权限：

- `admin`：管理 AI 配置、企业微信配置、API Key 和导入校验。
- `operator`：创建报价、查看审计、查看并处理人工任务。
- `sales`：创建普通报价和 AI 自动报价。
- `viewer`：只读审计和人工任务。

### 生产部署

生产 Compose 文件在 `infra/docker-compose.prod.yml`。推荐在服务器上使用独立
project name，避免影响同机其他容器：

```bash
cp infra/.env.prod.example .env.prod
# 修改 .env.prod 中的 POSTGRES_PASSWORD / DATABASE_URL / AI_CONFIG_SECRET
docker compose -p canada_quote --env-file .env.prod -f infra/docker-compose.prod.yml up -d --build
docker compose -p canada_quote --env-file .env.prod -f infra/docker-compose.prod.yml exec api \
  python scripts/create_api_key.py --name Admin --role admin
```

生产部署默认：

- Web 工作台：`WEB_PORT`，默认 `18080`。
- API：只绑定服务器本机 `127.0.0.1:API_PORT`，默认 `18000`。
- 前端通过 `/api` 反代访问后端，不需要浏览器直连 API 端口。
- 生产环境应保持 `DEV_AUTH_DISABLED=false`，并在前端顶部保存 `X-API-Key`。

## 报价 API

### Zone Quote

`POST /quotes/zone-calculate` 是当前 Canada final-mile MVP 的主报价入口。基础价必须来自
`zone_price_matrix`，查不到 Zone 或价格时返回 `manual_required`，不会按每托单价或里程估算。

```json
{
  "address_line": "8888 Keele St",
  "postal_code": "L4K 2N2",
  "city": "Concord",
  "province": "ON",
  "cbm": 4.2,
  "weight_kg": 850,
  "piece_count": 10,
  "packaging_type": "carton",
  "longest_side_cm": 100,
  "address_type": "commercial",
  "requires_liftgate": false,
  "requires_pallet_jack": false,
  "requires_appointment": true,
  "explicit_pallet_count": null
}
```

返回包含 `source_type`、`postal_prefix`、`origin`、`zone`、`billing_pallets`、
`base_price_usd`、`fuel_usd`、`accessorials`、`total_price_usd` 和 `matched_rule`。

每次 Zone 报价都会尝试写入 `quote_audit_logs`。如果报价结果是
`manual_required`，系统会自动创建 `manual_quote_tasks`，供运营人工确认。
审计或人工任务写入失败不会影响报价接口返回。

查询审计和人工任务：

```bash
GET /quotes/audit/{quote_id}
GET /quotes/manual-tasks
PATCH /quotes/manual-tasks/{task_id}
```

### AI Auto Quote

`POST /quotes/ai-auto-quote` 接收客户原始消息。流程是：

```text
客户原始消息
-> AI 提取结构化字段
-> 后端校验字段完整性
-> Zone Quote Engine 确定性报价
-> 写 audit / manual task
-> AI 只基于锁定 quote_result 润色销售话术
```

如果缺少 `postal_code`、`cbm`、`weight_kg`、`piece_count`、`packaging_type`
或 `address_type`，接口不会调用 Zone Quote Engine，只返回 `missing_fields`
和追问客户的话术。

AI 配置接口：

```bash
GET /ai-configs
POST /ai-configs
GET /ai-configs/{config_id}
PATCH /ai-configs/{config_id}
DELETE /ai-configs/{config_id}
POST /ai-configs/{config_id}/set-default
POST /ai-configs/{config_id}/test
```

`api_key` 存入 `ai_model_configs.api_key_encrypted`，接口只返回
`masked_api_key`，不会返回明文密钥。开发环境可通过 `AI_CONFIG_SECRET`
设置本地加密 secret；生产环境建议替换为 KMS 或更强的密钥管理。

### WeCom Bot Notify

企业微信机器人只负责通知和推送，不参与报价、不绕过 Quote Engine。
Webhook URL 存入 `wecom_bot_configs.webhook_url_encrypted`，接口只返回
`masked_webhook_url`，不会返回明文 URL。

配置接口：

```bash
GET /wecom/bots
POST /wecom/bots
GET /wecom/bots/{bot_id}
PATCH /wecom/bots/{bot_id}
DELETE /wecom/bots/{bot_id}
POST /wecom/bots/{bot_id}/set-default
POST /wecom/bots/{bot_id}/test
```

推送接入点：

- `/quotes/zone-calculate`：支持 wrapper body `{ "quote": {...}, "notify_wecom": true }`。
  普通成功报价仅在 `notify_wecom=true` 时推送；`manual_required=true` 会自动尝试推送人工确认通知。
- `/quotes/ai-auto-quote`：支持 `notify_wecom` 和 `wecom_bot_id`。
  成功报价可推送 AI 自动报价通知；字段缺失时仅在勾选后推送追问提示；`manual_required=true`
  会自动尝试推送人工确认通知。
- `/quotes/manual-tasks/{task_id}`：PATCH `status=resolved` 且 `notify_wecom=true`
  时推送人工报价已处理通知。

如果人工确认机器人启用了 `mention_all_on_manual_required`，系统会先推送 markdown
详情，再单独发送 `@all 有新的加拿大尾程报价需人工确认，请查看上一条详情。` 文本提醒。
所有企业微信推送失败都只记录日志，不影响报价或人工任务接口返回。

### Vendor Rate Rule Quote

`POST /quotes/calculate` 只接收 shipment，不接收用户传入的 `rate_rules`。
API 会从 PostgreSQL 查询候选 `vendor_rate_rules`，再交给 Quote Engine 计算。

```json
{
  "address_line": "8888 Keele St",
  "postal_code": "L4K 2N2",
  "city": "Concord",
  "province": "ON",
  "origin_warehouse": "Toronto",
  "pallet_count": 3,
  "weight_kg": 850,
  "requires_appointment": true,
  "requires_liftgate": false,
  "is_residential": false,
  "dock_available": null
}
```

命中时会返回 `source_type`、`confidence`、`matched_rule`、`cost_breakdown`
和锁定价格。未命中时返回 `manual_required`，价格字段为 `null`。

## 当前状态

仓库已初始化，Canada final-mile 报价资料已归档到 `reference/canada-final-mile/`，
并已建立第一版工程骨架、SQLAlchemy 数据访问闭环和 Zone Quote Engine。

## 资料入口

- 资料索引：`docs/reference-index.md`
- 实时报价 SOP：`reference/canada-final-mile/SOP_QUICK.md`
- 规则参数：`reference/canada-final-mile/RULES.yaml`
- 输出模板：`reference/canada-final-mile/QUOTE_TEMPLATE.md`
- 邮编/Zone/价格查表数据：`reference/canada-final-mile/`

## 下一步

- 增加真实导入模板和脱敏样例数据。
- 用 `EDGE_CASES.md` 建立异常场景测试集。
- 做极简前端报价工作台，使用审计日志和人工确认池支撑运营流程。
- 接入 Google Address Validation 或 Canada Post AddressComplete 前，保持人工确认兜底。
