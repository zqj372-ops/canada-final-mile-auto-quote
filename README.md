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
- 旧的同步“Agent 纠错”已降级为 `LLM 辅助建议`，不再作为主报价链路自动改价。
- 每次报价都会写入 `hermes_diagnostic_queue`，Hermes Agent 只读诊断包并输出建议。
- Hermes 自学习只生成候选建议；人工审核通过前，不会改写报价规则或自动放行价格。

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
ops/hermes/                        Hermes Agent 只读运维诊断脚本和提示词
reference/canada-final-mile/       已归档的业务资料和查表数据
tests/                             MVP 单元测试
```

## MVP 功能

- 读取并校验供应商报价表标准字段。
- 标准化加拿大邮编，例如 `v6v1a1 -> V6V 1A1 -> V6V`。
- 标准化省份，例如 `Ontario -> ON`、`British Columbia -> BC`。
- 按 Zone 查表链路报价：
  `postal_code override -> FSA single-zone -> FSA + city_alias/canonical_city -> city fallback -> zone_price_matrix`
- 分区价格支持全局总开关、默认最高自动报价 Zone（默认 7），以及每个 `始发仓 + Zone` 的独立覆盖开关。
  默认 Zone 1–7 开启、Zone 8 及以上关闭；关闭只暂停自动报价并转人工复核，原价格矩阵不会被删除，人工学习规则也不能绕过开关。
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

前端默认请求 `/api`；本地 Vite 会代理到 `http://localhost:8000`。如需修改 API 地址：

```bash
VITE_API_BASE_URL=http://localhost:8000 npm run dev
```

工作台页面：

- `/quote`：普通 Zone 报价输入。
- `/ai-quote`：粘贴客户原始消息，由 AI 提取字段，再由 Zone Quote Engine 报价。
- `/manual-tasks`：处理 `manual_required` 人工确认任务。
- `/learning-candidates`：Hermes 自学习候选审核，批准后才发布为可复用学习规则。
- `/audit`：按 `quote_id` 查询报价审计记录。
- `/settings/quote`：维护 `/quote` 工作台后台配置，包括示例、字段选项、风险阈值和复制话术。
- `/settings/cities`：按始发仓和 Zone 维护城市、FSA 邮编前缀及标准城市名。
- `/settings/ai`：维护 OpenAI-compatible 模型配置，支持输入 API Key 自动获取模型列表并导入，也可为内置 Hermes Agent 独立切换已加密保存的 Key/模型配置。
- `/settings/search`：维护 Tavily 等搜索 API Key，用于 AI 自动报价时查询地址和行情参考。
- `/settings/wecom`：维护企业微信群机器人 Webhook 配置。
- `/settings/email`：维护邮件通知配置，作为人工任务和报价通知的主要通道。

`/quote` 是中文 AI 报价工作台：销售粘贴尺寸、重量、地址和邮编，页面只做字段识别
和展示，价格仍由后端 `POST /quotes/zone-calculate` 计算。包装类型、地址类型、风险
阈值、示例文本、附加费显示名和报价复制模板由后端
`GET /quote-configs/workbench` 返回，不写死在前端。

Docker Compose：

```bash
cp .env.example .env
docker compose -f infra/docker-compose.yml up --build
```

### Quote release readiness

`/health` 只表示进程存活；`/api/status` 才是报价发布就绪门禁，并且只接受带有
`quote:preview` scope 的 `X-API-Key`。0026 迁移会停用旧 manifest；没有经过受控发布的
active manifest 时，状态保持 `ready=false`，不会输出可用报价。

生产 `.env.prod` 必须提供 `QUOTE_RELEASE_ID`，但本仓库不保存生产值。数据和构建完成后，
由操作员在目标环境执行一次发布命令：

```bash
python scripts/publish_quote_release.py \
  --release-id "$QUOTE_RELEASE_ID" \
  --service-version "$(python -c 'from importlib import metadata; print(metadata.version("canada-final-mile-auto-quote"))')" \
  --rule-version "<published-rule-version>" \
  --data-version "<published-data-version>" \
  --published-at "<UTC ISO-8601 timestamp>" \
  --valid-from "<YYYY-MM-DD>" \
  --valid-to "<YYYY-MM-DD>" \
  --test-data false
```

发布事务只计算一次 source snapshot hash，并把显式 `--test-data` 与数据标记检测取逻辑或；
检测到 demo、fixture、mock、sample 或 test 标记时仍会保持 `test_data=true`。发布后必须用
`/api/status` 验证 `ready=true`、`test_data=false` 和 snapshot hash；CI 部署同时检查
`/health` 与该 readiness 门禁。

## GitHub 自动部署

推送到生产分支后，GitHub Actions 会先运行完整测试、数据库迁移验证和前端构建；
全部通过后自动同步到生产服务器、重建 API/Web 容器并检查公网健康状态。服务器无需
手工 `git pull`。Secrets、分支策略、部署版本记录和回退方法见
[GitHub 自动部署说明](docs/GITHUB_DEPLOYMENT.md)。

本地 Compose 会在 API 启动前自动执行 `alembic upgrade head`。如需加载演示数据：

```bash
docker compose -f infra/docker-compose.yml exec -T postgres \
  sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < infra/postgres/seed.sql
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

数据库结构只通过 `migrations/versions/` 里的 Alembic migration 管理，
`infra/postgres/seed.sql` 仅提供可选演示数据。单元测试使用 SQLite 内存库，并由
`Base.metadata.create_all()` 自动建表；CI 另外会在真实 Postgres 上从空库执行完整迁移链。

旧版 Compose 曾用 `init.sql` 直接建表。如果本机仍是一次性演示数据，可先执行
`docker compose -f infra/docker-compose.yml down -v` 清理旧卷后重新启动；有需要保留的
数据时应先备份并核对迁移版本，不要直接把未知结构 `stamp head`。

## Hermes Agent 运维助手

服务器上可安装 NousResearch Hermes Agent 作为报价服务的只读运维副驾驶。仓库内
`ops/hermes/` 提供固定诊断脚本和提示词，减少 Hermes 临时拼命令造成误判。

常用命令：

```bash
ops/hermes/scripts/check_health.sh
ops/hermes/scripts/check_recent_errors.sh 120
ops/hermes/scripts/check_manual_tasks.sh
ops/hermes/scripts/check_hermes_diagnostics.sh pending 20
ops/hermes/scripts/check_learning_candidates.sh
ops/hermes/scripts/check_zone_match.sh S7K Saskatoon SK
ops/hermes/scripts/quote_debug_snapshot.sh <quote_id>
ops/hermes/run_daily_report.sh
```

默认面向 Oracle 部署：

```text
HERMES_PUBLIC_URL=https://quote.freightclaw.net
HERMES_COMPOSE_PROJECT=canada_quote_oracle
HERMES_COMPOSE_FILE=infra/docker-compose.prod.yml
HERMES_ENV_FILE=.env.prod
```

Hermes 只能诊断、总结、提出修复建议；不能编造价格，不能改写报价金额，不能输出
密钥或解密后的配置。报价金额仍然只能来自 Quote Engine、Zone 价格矩阵或已审核的
`learned_quote_rules`。

后台的“AI 模型配置”页面可为 Hermes 选择独立的模型配置。该绑定不会改动
AI 报价的通用默认模型；Hermes 未单独绑定时，内置 LLM 辅助诊断链路会回退到通用默认配置。

新的 Hermes 运行边界：

```text
报价成功/失败
-> 写入 hermes_diagnostic_queue
-> Hermes Agent 只读诊断包
-> 输出是否可纠错、建议 Zone、缺失表、是否建议人工、是否建议学习
-> 人工确认价格
-> 生成 hermes_learning_candidates
-> 审核批准后发布 learned_quote_rules
```

诊断包会包含原始输入、解析结果、邮编/城市/省份、Zone 命中、价格矩阵、
失败原因、相邻 FSA、历史人工确认和私有地址参考包的小上下文。主报价接口不会等待
Hermes Agent，避免慢响应或 504。

### 参考数据导入

生产和开发库可通过 admin-only 导入接口维护 Zone 参考数据。导入只更新结构化表，
不会把完整价格表交给 AI，也不会让 AI 参与价格计算。

```bash
POST /imports/zone-rules
POST /imports/zone-price-matrix
POST /imports/postal-code-lookup
POST /imports/city-aliases
```

四个接口都接收 `.json` 文件并执行 upsert，返回：

```json
{
  "status": "imported",
  "resource": "zone_lookup_rules",
  "row_count": 1,
  "inserted_count": 1,
  "updated_count": 0,
  "skipped_count": 0
}
```

`zone_lookup_rules` 支持 `canonical_city`、`priority`、`active`。`city_aliases`
用于把客户输入城市和供应商/邮编库城市统一，例如 `CONCORD -> VAUGHAN`。
`postal_zone_overrides` 用于完整邮编特殊覆盖，优先级高于 FSA 和城市匹配。

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

- `admin`：管理 AI 配置、企业微信配置、API Key 和参考数据导入。
- `operator`：创建报价、查看审计、查看并处理人工任务。
- `sales`：创建普通报价和 AI 自动报价。
- `viewer`：只读审计和人工任务。

前台和后台应使用不同的 API Key：

- `/quote` 前台报价工作台保存“前台 Key”，建议使用 `sales` 角色。
- `/admin` 及后台配置、审计、人工任务页面保存“后台 Key”，按职责使用 `admin`、`operator`
  或 `viewer` 角色。
- 前端会把两类 Key 存在不同的浏览器本地存储项中，互不覆盖。

报价工作台配置接口：

```bash
GET /quote-configs/workbench
PUT /quote-configs/workbench
```

读取配置允许所有角色；更新配置仅允许 `admin`。配置存储在 `quote_rule_config`
表的 `quote_workbench_config` 记录中，前端不得维护另一份业务配置。

### 生产部署

生产 Compose 文件在 `infra/docker-compose.prod.yml`。推荐在服务器上使用独立
project name，避免影响同机其他容器：

```bash
cp infra/.env.prod.example .env.prod
# 修改 .env.prod 中的 POSTGRES_PASSWORD / DATABASE_URL / AI_CONFIG_SECRET / AUTH_TOKEN_SECRET / QUOTE_RELEASE_ID
docker compose -p canada_quote --env-file .env.prod -f infra/docker-compose.prod.yml up -d --build
docker compose -p canada_quote --env-file .env.prod -f infra/docker-compose.prod.yml exec api \
  python scripts/create_user.py \
    --username admin@example.com \
    --password 'change-this-admin-password' \
    --display-name Admin \
    --role admin \
    --update-if-exists
docker compose -p canada_quote --env-file .env.prod -f infra/docker-compose.prod.yml exec api \
  python scripts/create_user.py \
    --username sales@example.com \
    --password 'change-this-sales-password' \
    --display-name Sales \
    --role sales \
    --update-if-exists
```

生产部署默认：

- Web 工作台：只绑定服务器本机 `127.0.0.1:WEB_PORT`，默认 `18080`。
- API：只绑定服务器本机 `127.0.0.1:API_PORT`，默认 `18000`。
- 前端通过 `/api` 反代访问后端，不需要浏览器直连 API 端口。
- 生产环境应保持 `DEV_AUTH_DISABLED=false`；前台 `/quote` 使用销售、运营或管理员
  账号登录，后台 `/admin` 使用管理员、运营或查看者账号登录。
- 旧的 API Key 仍可用于接口级自动化调用；Web 前后台默认走账号密码登录。
- 如果挂在已有域名子路径下，可设置 `VITE_APP_BASE_PATH=/canada-quote/`
  和 `VITE_API_BASE_URL=/canada-quote-api` 后重建 Web 容器。

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
`base_price_usd`、`fuel_usd`、`accessorials`、`total_price_usd`、`matched_rule`、
`matched_by`、`candidate_count` 和 `match_trace`。

Zone 匹配优先级：

```text
full postal_code override
-> FSA 下只有一个 origin + zone 时直接命中
-> FSA + canonical_city / city_alias 命中
-> 兼容旧数据的 city fallback
-> manual_required
```

如果同一 FSA 下存在多个 origin/zone 且城市别名仍无法唯一确定，系统返回
`manual_required`，不会估算价格。

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
-> 可选 Tavily 搜索地址情况 / 市场行情参考
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
GET /ai-configs/provider-presets
POST /ai-configs/discover-models
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

搜索配置接口：

```bash
GET /search-configs
POST /search-configs
PATCH /search-configs/{config_id}
DELETE /search-configs/{config_id}
POST /search-configs/{config_id}/set-default
POST /search-configs/{config_id}/test
```

搜索 API Key 存入 `search_api_configs.api_key_encrypted`，接口只返回
`masked_api_key`。搜索结果只能进入 AI 的参考上下文，用于描述地址风险、偏远性或市场行情背景；
不能替代 `zone_price_matrix`，不能新增费用，也不能改变 Quote Engine 返回的金额。

### Email Notify

邮件通知只负责推送报价结果和人工任务提醒，不参与报价、不绕过 Quote Engine。
SMTP 密码存入 `email_notification_configs.password_encrypted`，接口只返回
`has_password` 和掩码用户名，不会返回明文密码。

配置接口：

```bash
GET /email/configs
POST /email/configs
GET /email/configs/{config_id}
PATCH /email/configs/{config_id}
DELETE /email/configs/{config_id}
POST /email/configs/{config_id}/set-default
POST /email/configs/{config_id}/test
```

推送接入点：

- `/quotes/zone-calculate`：支持 wrapper body `{ "quote": {...}, "notify_email": true }`。
  普通成功报价仅在 `notify_email=true` 时发送邮件；`manual_required=true` 会自动尝试发送人工确认邮件。
- `/quotes/ai-auto-quote`：支持 `notify_email` 和 `email_config_id`。
  成功报价可发送 AI 自动报价通知；字段缺失时仅在勾选后发送追问提示；`manual_required=true`
  会自动尝试发送人工确认邮件。
- `/quotes/manual-tasks/{task_id}`：PATCH `status=resolved` 且 `notify_email=true`
  时推送人工报价已处理通知。

邮件配置按 `purpose` 匹配，找不到时使用默认配置。旧企业微信接口仍保留为兼容回退；
所有通知失败都只记录日志，不影响报价或人工任务接口返回。

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
- Hermes 自学习边界：`docs/HERMES_LEARNING.md`
- 实时报价 SOP：`reference/canada-final-mile/SOP_QUICK.md`
- 规则参数：`reference/canada-final-mile/RULES.yaml`
- 输出模板：`reference/canada-final-mile/QUOTE_TEMPLATE.md`
- 邮编/Zone/价格查表数据：`reference/canada-final-mile/`

## 下一步

- 增加真实导入模板和脱敏样例数据。
- 用 `EDGE_CASES.md` 建立异常场景测试集。
- 做极简前端报价工作台，使用审计日志和人工确认池支撑运营流程。
- 接入 Google Address Validation 或 Canada Post AddressComplete 前，保持人工确认兜底。
