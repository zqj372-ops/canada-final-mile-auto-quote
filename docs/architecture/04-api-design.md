# REST API 设计

## 1. 合约原则

- Base URL：`/api/v1`。
- OpenAPI 3.x 是外部和前端合约的唯一来源；CI 生成 TypeScript SDK 并检查 breaking changes。
- 资源查询使用 REST；具有业务含义的状态转换使用显式 command 子资源，例如 `/submit`、`/approve`、`/publish`。
- API 不暴露 Prisma model；Request/Response DTO 是应用层稳定合约。
- 所有写接口记录 `X-Request-Id`、Actor、Organization 和 Audit Log。
- 创建、发布、接受、分配、状态更新等命令要求 `Idempotency-Key`。
- 可变 Aggregate 更新要求 `If-Match: "<version>"`；版本冲突返回 `409`。
- 金额以字符串传输，避免 JavaScript 浮点误差，例如 `"1250.0000"`。
- DateTime 使用 ISO 8601 UTC；Date 使用 `YYYY-MM-DD`。
- 外部输入的重量/体积可带单位；响应统一返回 kg/cbm。

## 2. 认证与组织上下文

### 2.1 Token

- 用户登录：短时 Access JWT + 可轮换的 Refresh Token；数据库只保存 Refresh Token hash。
- API Client：`client_id + secret` 换取短时 JWT；secret 只在创建时显示一次。
- JWT 最小 claims：`sub`, `actor_type`, `session_id/client_id`, `org_ids`, `iat`, `exp`, `jti`。
- 当前组织由 `X-Organization-Id` 指定，并必须存在于 JWT 可访问组织集合。

### 2.2 默认角色

| 角色 | 代码 | 典型权限 |
| --- | --- | --- |
| 客户 | `CUSTOMER` | 维护本组织需求、查看/接受本组织报价、订单和 Timeline |
| 销售 | `SALES` | 管理被分配客户需求、查看成本、生成/发布报价 |
| 供应商 | `SUPPLIER` | 查看发给本组织的 RFQ、提交报价、处理本组织 Task |
| 管理员 | `ADMIN` | 目录、组织、角色、供应商、策略、集成、审计管理 |
| 系统 | `SYSTEM` | Worker/内部 API；仅限明确 scopes |

权限是 `module.resource.action` 字符串，例如 `rfq.invitation.read`、`fulfillment.task.update_own`、`pricing.policy.approve`。角色只是权限集合，Controller 不硬编码角色名。

## 3. 通用协议

### 3.1 请求头

| Header | 适用 | 说明 |
| --- | --- | --- |
| `Authorization: Bearer <jwt>` | 除公开回调外 | 用户/API Client Access Token |
| `X-Organization-Id` | 组织级资源 | 当前组织上下文 |
| `X-Request-Id` | 全部 | 客户端可传；无则服务端生成 |
| `Idempotency-Key` | 写命令 | 同组织内唯一；相同 key + 不同 body 返回 `409` |
| `If-Match: "7"` | PATCH/状态命令 | Aggregate 当前 version |
| `Accept-Language` | 展示型响应 | `en-CA`, `fr-CA`, `zh-CN` 等 |

### 3.2 成功响应

单资源：

```json
{
  "data": {
    "id": "018f...",
    "version": 3,
    "status": "SUBMITTED"
  },
  "meta": {
    "requestId": "req_01..."
  }
}
```

Cursor 分页：

```json
{
  "data": [],
  "meta": {
    "nextCursor": "eyJpZCI6Ii4uLiJ9",
    "hasMore": false,
    "requestId": "req_01..."
  }
}
```

默认 `limit=25`，最大 `100`。Cursor 是不透明值，不允许客户端解析或构造。

### 3.3 错误响应

使用 Problem Details 结构并增加稳定业务码：

```json
{
  "type": "https://api.example.com/problems/plan-validation-failed",
  "title": "Logistics plan validation failed",
  "status": 422,
  "code": "PLAN_VALIDATION_FAILED",
  "detail": "Two required services are not connected.",
  "instance": "/api/v1/logistics-plans/018f.../approve",
  "requestId": "req_01...",
  "errors": [
    {
      "path": "legs[4]",
      "code": "UNREACHABLE_REQUIRED_SERVICE",
      "message": "IMPORT_CUSTOMS is not connected to final mile."
    }
  ]
}
```

| HTTP | 场景 |
| --- | --- |
| `400` | JSON/查询参数格式错误 |
| `401` | 未认证或 Token 失效 |
| `403` | 组织/权限/资源归属不允许 |
| `404` | 资源不存在或为防枚举而隐藏 |
| `409` | version/idempotency/状态冲突 |
| `422` | 业务不变量或确定性校验失败 |
| `429` | 限流 |
| `503` | 必需依赖暂不可用；不会伪造业务结果 |

## 4. API 端点清单

角色缩写：C=Customer，S=Sales，V=Supplier，A=Admin，Y=System/Worker。

### 4.1 Auth、用户、组织与 RBAC

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/auth/login` | Public | Email/password 登录，返回 Access + Refresh |
| POST | `/auth/refresh` | Public | Refresh rotation；复用旧 Token 会撤销 family |
| POST | `/auth/logout` | C/S/V/A | 撤销当前 Session |
| POST | `/auth/client-token` | API Client | Client credentials 换 JWT |
| GET | `/me` | C/S/V/A | 当前用户、组织和 Membership |
| GET | `/me/permissions` | C/S/V/A | 当前组织有效权限 |
| GET | `/organizations` | A；成员仅自己 | 查询可见组织 |
| POST | `/organizations` | A | 创建客户/供应商/平台组织 |
| GET | `/organizations/{organizationId}` | A；成员自己 | 组织详情 |
| PATCH | `/organizations/{organizationId}` | A/Org Owner | 乐观锁更新 |
| GET | `/organizations/{organizationId}/memberships` | A/Org Owner | 成员列表 |
| POST | `/organizations/{organizationId}/invitations` | A/Org Owner | 邀请用户并授予角色 |
| POST | `/invitations/{token}/accept` | Public | 接受邀请 |
| PATCH | `/memberships/{membershipId}/roles` | A/Org Owner | 角色赋权 |
| GET | `/roles` | A/Org Owner | 平台与本组织角色 |
| POST | `/roles` | A/Org Owner | 新增组织角色 |
| PATCH | `/roles/{roleId}` | A/Org Owner | 修改自定义角色 |
| GET | `/permissions` | A/Org Owner | 权限字典 |
| POST | `/organizations/{organizationId}/api-clients` | A/Org Owner | 创建 API Client；secret 只返回一次 |
| PATCH | `/api-clients/{apiClientId}` | A/Org Owner | 禁用/轮换/撤销 |

### 4.2 服务市场与供应商能力

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/service-categories` | C/S/V/A | 服务分类与排序 |
| POST | `/service-categories` | A | 新增分类 |
| GET | `/services` | C/S/V/A | 按 category/stage/status 查询服务 |
| POST | `/services` | A | 新增服务定义和输入 Schema |
| GET | `/services/{serviceId}` | C/S/V/A | 服务定义、选项和关系 |
| PATCH | `/services/{serviceId}` | A | 新 revision/状态调整 |
| POST | `/services/{serviceId}/relationships` | A | 新增依赖/先后/排斥/替代 |
| DELETE | `/service-relationships/{relationshipId}` | A | 逻辑停用关系 |
| GET | `/supplier-offerings` | S/V/A | 按 service/coverage/supplier 查询 |
| POST | `/supplier-offerings` | V/A | 新建本供应商 Offering |
| PATCH | `/supplier-offerings/{offeringId}` | V-own/A | 修改能力/货量/状态 |
| POST | `/supplier-offerings/{offeringId}/coverages` | V-own/A | 新增覆盖范围 |
| PATCH | `/supplier-coverages/{coverageId}` | V-own/A | 修改/停用 Coverage |
| GET | `/facilities` | C/S/V/A | 可见 Warehouse/CFS/Ramp |
| POST | `/facilities` | V/A | 新建设施 |
| PATCH | `/facilities/{facilityId}` | V-own/A | 更新容量/能力/状态 |

### 4.3 Shipment Request 与 AI Logistics Plan

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/shipment-requests` | C/S/A | 创建草稿；可原子提交 cargo/items/services |
| GET | `/shipment-requests` | C-own/S-assigned/A | 筛选 status/date/customer/destination |
| GET | `/shipment-requests/{requestId}` | C-own/S-assigned/A | 需求详情 |
| PATCH | `/shipment-requests/{requestId}` | C-own/S-assigned/A | 仅 DRAFT 可改核心字段 |
| POST | `/shipment-requests/{requestId}/submit` | C-own/S/A | 完整性校验并异步触发 Planning |
| POST | `/shipment-requests/{requestId}/cancel` | C-own/S/A | 按当前状态执行取消策略 |
| POST | `/shipment-requests/{requestId}/logistics-plans` | S/A/Y | 生成新 plan revision；返回 `202 + operationId` |
| GET | `/shipment-requests/{requestId}/logistics-plans` | C-own/S/A | Plan revisions |
| GET | `/logistics-plans/{planId}` | C-own/S/A | Plan、legs、dependencies、validation |
| POST | `/logistics-plans/{planId}/validate` | S/A/Y | 运行确定性校验，不改变批准状态 |
| POST | `/logistics-plans/{planId}/approve` | S/A | 必须校验通过；固化 revision |
| POST | `/logistics-plans/{planId}/reject` | S/A | 拒绝并写 reason |
| GET | `/operations/{operationId}` | C/S/V/A | 查询异步操作状态和目标资源 |

### 4.4 RFQ 与自动选商/分发

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/rfqs` | S/A | 从 approved plan 创建 RFQ round |
| GET | `/rfqs` | S/A；V 走 supplier 端点 | 查询开放/到期/响应状态 |
| GET | `/rfqs/{rfqId}` | S/A | RFQ、items、invitations |
| GET | `/rfqs/{rfqId}/supplier-candidates` | S/A | 候选、Coverage、KPI、过滤理由 |
| POST | `/rfqs/{rfqId}/invitations` | S/A | 选择供应商和 primary channel |
| POST | `/rfqs/{rfqId}/publish` | S/A | 发布并写 Dispatch Requested Outbox |
| POST | `/rfqs/{rfqId}/close` | S/A | 截止接收新回复 |
| POST | `/rfq-invitations/{invitationId}/resend` | S/A | 新 dispatch attempt；幂等 |
| GET | `/rfq-invitations/{invitationId}/dispatch-attempts` | S/A | 渠道投递审计 |
| GET | `/supplier/rfq-invitations` | V-own | 供应商 RFQ Inbox |
| GET | `/supplier/rfq-invitations/{invitationId}` | V-own | 脱敏 RFQ 详情 |
| POST | `/supplier/rfq-invitations/{invitationId}/decline` | V-own | 拒绝及原因 |

### 4.5 供应商报价、文件接入与 AI 解析

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/supplier/rfq-invitations/{invitationId}/quotes` | V-own | Portal/API 提交结构化报价 revision |
| POST | `/rfq-invitations/{invitationId}/reply-files` | V-own/S/A/Y | 上传 Email/Excel/PDF 原始回复并触发 Parse |
| GET | `/supplier-quotes` | S/A；V-own | 按 RFQ/supplier/status 查询 |
| GET | `/supplier-quotes/{quoteId}` | S/A；V-own | 标准化报价、items、charges、lineage |
| POST | `/supplier-quotes/{quoteId}/revisions` | V-own/S/A | 创建新 revision，不覆盖旧版 |
| POST | `/quote-parse-runs` | S/A/Y | 对已上传文件触发解析；`202` |
| GET | `/quote-parse-runs/{parseRunId}` | S/A；V-own limited | 状态、置信度、校验错误 |
| POST | `/quote-parse-runs/{parseRunId}/retry` | S/A | 新 AI Run；旧 Run 保留 |
| POST | `/quote-parse-runs/{parseRunId}/resolve` | S/A | 人工更正候选并验证；记录 before/after |
| POST | `/supplier-quotes/{quoteId}/submit` | V-own/S/A | 通过确定性校验后成为可用成本 revision |
| POST | `/supplier-quotes/{quoteId}/withdraw` | V-own/S/A | 撤回，不删除 |

### 4.6 Customer Quote Center

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/shipment-requests/{requestId}/customer-quotes` | S/A | 从 approved plan + validated supplier quotes 生成 revision |
| GET | `/customer-quotes` | C-own/S/A | 查询报价 |
| GET | `/customer-quotes/{quoteId}` | C-own/S/A | 方案及客户可见费用；成本仅 S/A |
| GET | `/customer-quotes/{quoteId}/comparison` | C-own/S/A | 标准化比较矩阵 |
| POST | `/customer-quotes/{quoteId}/publish` | S/A | 价格护栏、有效期、完整性校验后发布 |
| POST | `/customer-quotes/{quoteId}/revisions` | S/A | 复制快照并创建新 revision |
| POST | `/customer-quotes/{quoteId}/acceptances` | C-own/S-assisted | 接受一个 Option；幂等创建 Order |
| POST | `/customer-quotes/{quoteId}/decline` | C-own/S | 记录原因 |
| GET | `/quote-options/{optionId}/price-explanation` | C-own/S/A | 受权限控制的价格/风险说明 |

### 4.7 拼货、价格锁与 Order

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/orders` | C-own/S/A | 订单列表 |
| GET | `/orders/{orderId}` | C-own/S/A | 商业订单与分配 Shipment |
| POST | `/orders/{orderId}/cancel` | C-own/S/A | 根据履约阶段执行取消/人工流程 |
| GET | `/consolidation-pools` | S/A | 目的地、开仓时间、当前/剩余 kg/cbm |
| POST | `/consolidation-pools` | S/A | 创建计划池 |
| PATCH | `/consolidation-pools/{poolId}` | S/A | 乐观锁更新容量/时间/状态 |
| GET | `/orders/{orderId}/pool-candidates` | S/A/Y | 匹配候选和理由 |
| POST | `/consolidation-pools/{poolId}/memberships` | S/A/Y | 加入 Candidate/Reserve；容量事务校验 |
| POST | `/pool-memberships/{membershipId}/confirm` | S/A | 确认占用 |
| POST | `/pool-memberships/{membershipId}/release` | S/A | 释放容量 |
| POST | `/consolidation-pools/{poolId}/confirm` | S/A | 固化拼仓、创建/关联 Shipment |
| POST | `/price-locks` | S/A/Y | 锁定 BUY 或 SELL 价格 |
| POST | `/price-locks/{priceLockId}/consume` | S/A/Y | Order/Shipment 使用价格锁 |
| POST | `/price-locks/{priceLockId}/release` | S/A | 释放未使用锁 |

### 4.8 Shipment、履约任务和供应商工作台

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/shipments` | C-own/S/A；V-assigned | Shipment 查询 |
| GET | `/shipments/{shipmentId}` | C-own/S/A；V-assigned limited | 运营编组、任务摘要、Timeline |
| POST | `/shipments/{shipmentId}/fulfillment-tasks` | S/A/Y | 从 Plan 生成任务；幂等 |
| GET | `/fulfillment-tasks` | S/A | 内部任务队列 |
| GET | `/supplier/fulfillment-tasks` | V-own | 强制当前 supplier organization filter |
| GET | `/supplier/fulfillment-tasks/{taskId}` | V-own | 仅本供应商任务；不返回其他腿成本 |
| POST | `/supplier/fulfillment-tasks/{taskId}/accept` | V-own | 接受任务 |
| POST | `/supplier/fulfillment-tasks/{taskId}/reject` | V-own | 拒绝并说明 |
| POST | `/supplier/fulfillment-tasks/{taskId}/start` | V-own | 前置依赖校验 |
| POST | `/supplier/fulfillment-tasks/{taskId}/complete` | V-own | 完成、证据文件/时间/地点 |
| POST | `/supplier/fulfillment-tasks/{taskId}/exceptions` | V-own | 报告异常 |
| POST | `/fulfillment-tasks/{taskId}/resolve-exception` | S/A | 处理异常并恢复/取消 |
| GET | `/fulfillment-tasks/{taskId}/history` | S/A；V-own | 追加式状态历史 |

### 4.9 Tracking

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/shipments/{shipmentId}/timeline` | C-own/S/A；V-assigned | 合并 Milestone + Event，按时间排序 |
| GET | `/shipments/{shipmentId}/milestones` | C-own/S/A；V-assigned | 计划/预计/实际节点 |
| POST | `/shipments/{shipmentId}/tracking-events` | S/A；V-assigned/Y | 标准化 Event；外部 id 去重 |
| POST | `/webhooks/inbound/tracking/{connectionId}` | Signed external | Carrier/Supplier webhook；先验签再归一化 |
| POST | `/tracking-events/{eventId}/attachments` | V-own/S/A | POD、照片、文件引用 |

### 4.10 Supplier Center

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/suppliers` | S/A | 搜索能力、地区、风险、KPI |
| POST | `/suppliers` | A | 创建 Supplier Organization/Profile |
| GET | `/suppliers/{supplierId}` | S/A；V-own | 档案、能力、资质、当前 KPI |
| PATCH | `/suppliers/{supplierId}` | A；V-own limited | 修改档案/支付条件/风险需不同权限 |
| POST | `/suppliers/{supplierId}/contacts` | A；V-own | 联系人 |
| POST | `/suppliers/{supplierId}/certifications` | A；V-own | 资质与文件 |
| GET | `/suppliers/{supplierId}/complaints` | S/A；V-own limited | 投诉、严重度、处理状态 |
| POST | `/suppliers/{supplierId}/complaints` | C-own/S/A | 针对 Order/Shipment/Task 创建投诉 |
| POST | `/supplier-complaints/{complaintId}/resolve` | S/A | 结构化结案并触发 KPI 重算 |
| GET | `/suppliers/{supplierId}/kpis` | S/A；V-own limited | 响应率、成交率、履约率、投诉率等 |
| POST | `/suppliers/{supplierId}/kpi-recalculations` | A/Y | 异步重算指定窗口 |

### 4.11 Price Intelligence

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| GET | `/price-intelligence/observations` | A/Price Analyst | 按 source/segment/date/quality 查询；私密数据严格授权 |
| POST | `/price-intelligence/observations/imports` | A/Y | 导入历史/价卡；保留 lineage |
| POST | `/price-intelligence/observations/{id}/corrections` | A | 追加 superseding observation，不 UPDATE 原事实 |
| GET | `/price-intelligence/forecasts` | S/A | city/service/horizon=7,14,30 查询 |
| POST | `/price-intelligence/forecast-runs` | A/Y | 训练/推理 Job；返回 operation |
| GET | `/price-intelligence/forecast-models` | A | Candidate/Shadow/Active 模型 |
| POST | `/price-intelligence/forecast-models/{id}/activate` | A + approver | 通过回测门槛后激活 |
| POST | `/price-intelligence/recommendations` | S/A/Y | 生成销售价或采购目标建议 |
| GET | `/price-intelligence/recommendations/{id}` | S/A | 区间、置信度、原因和 evidence |
| POST | `/price-intelligence/recommendations/{id}/approve` | S/A | 按阈值审批 |
| GET | `/price-intelligence/dynamic-pricing-policies` | A | 策略列表 |
| POST | `/price-intelligence/dynamic-pricing-policies` | A | Draft policy |
| PATCH | `/price-intelligence/dynamic-pricing-policies/{id}` | A | 新 version/状态 |
| POST | `/price-intelligence/dynamic-pricing-policies/{id}/shadow` | A | Shadow evaluation |
| POST | `/price-intelligence/dynamic-pricing-policies/{id}/activate` | A + approver | 双人/显式审批建议 |
| POST | `/price-intelligence/pricing-simulations` | S/A | 不写 Quote 的 What-if 模拟 |
| GET | `/pricing-decisions/{decisionId}` | S/A | 输入快照、因子、Guardrail、审批 |
| POST | `/pricing-decisions/{decisionId}/approve` | Authorized approver | 通过后才可应用到新 Quote revision |

### 4.12 文件、集成、Webhook、通知、审计与 Dashboard

| Method | Path | 角色 | 说明 |
| --- | --- | --- | --- |
| POST | `/files/upload-requests` | C/S/V/A | 获取短时预签名上传 URL |
| POST | `/files/{fileId}/complete` | C/S/V/A | 校验 size/hash，进入病毒扫描 |
| GET | `/files/{fileId}/download-url` | Authorized owner | 短时下载 URL；不暴露永久 S3 URL |
| POST | `/files/{fileId}/links` | Authorized owner | 将已扫描文件关联到 Quote/Task/Event/Complaint |
| GET | `/integration-connections` | A；V-own limited | 连接列表，不返回解密 secret |
| POST | `/integration-connections` | A；V-own limited | 创建 Email/API/Webhook/Excel 连接 |
| POST | `/integration-connections/{id}/verify` | A；V-own limited | 连接测试，写结果 |
| PATCH | `/integration-connections/{id}` | A；V-own limited | 更新/禁用/轮换密钥 |
| GET | `/webhook-subscriptions` | A/Org Owner | Outbound subscription |
| POST | `/webhook-subscriptions` | A/Org Owner | 创建事件订阅 |
| POST | `/webhook-subscriptions/{id}/rotate-secret` | A/Org Owner | Secret rotation |
| GET | `/webhook-deliveries` | A/Org Owner | 投递审计与 DLQ |
| POST | `/webhook-deliveries/{id}/retry` | A/Org Owner | 显式重试 |
| GET | `/notifications` | C/S/V/A | 当前用户通知 |
| POST | `/notifications/{id}/read` | C/S/V/A | 标记已读 |
| GET | `/review-tasks` | S/A | AI/价格/履约人工任务队列 |
| POST | `/review-tasks/{id}/assign` | S/A | 领取/转派 |
| POST | `/review-tasks/{id}/resolve` | S/A | 结构化结论 |
| GET | `/audit-logs` | A/Auditor | 按 actor/entity/correlation/time 查询 |
| GET | `/dashboards/operations` | S/A | RFQ/报价/池/履约聚合读模型 |
| GET | `/dashboards/price-intelligence` | S/A | Forecast、市场热度、推荐采用率、误差 |
| GET | `/dashboards/suppliers` | S/A | Supplier KPI 与风险 |

## 5. 关键 DTO 示例

### 5.1 创建 Shipment Request

```json
{
  "customerOrganizationId": "3f5e...",
  "origin": {
    "countryCode": "CN",
    "provinceState": "Zhejiang",
    "city": "Ningbo",
    "postalCode": "315000"
  },
  "destination": {
    "countryCode": "CA",
    "provinceState": "ON",
    "city": "Toronto",
    "postalCode": "M5V 2T6"
  },
  "cargo": {
    "cargoType": "GENERAL",
    "description": "Consumer goods",
    "totalWeight": { "value": "2400.0000", "unit": "KG" },
    "totalVolume": { "value": "12.5000", "unit": "CBM" },
    "pieces": 120,
    "hazardous": false
  },
  "readyWindow": {
    "from": "2026-07-20T01:00:00Z",
    "until": "2026-07-22T09:00:00Z"
  },
  "requestedServices": [
    { "code": "PICKUP", "requirementLevel": "REQUIRED" },
    { "code": "EXPORT_CUSTOMS", "requirementLevel": "REQUIRED" },
    { "code": "LCL", "requirementLevel": "REQUIRED" },
    { "code": "BOND", "requirementLevel": "PREFERRED" },
    { "code": "TORONTO_WAREHOUSE", "requirementLevel": "REQUIRED" },
    { "code": "LTL", "requirementLevel": "REQUIRED" }
  ]
}
```

### 5.2 Logistics Plan

```json
{
  "data": {
    "id": "plan_...",
    "revision": 1,
    "generationMode": "HYBRID",
    "status": "REVIEW_REQUIRED",
    "validation": {
      "valid": false,
      "errors": [],
      "warnings": ["BOND_REQUIRES_BONDED_FACILITY_SELECTION"]
    },
    "legs": [
      { "sequence": 1, "serviceCode": "PICKUP", "from": "Ningbo", "to": "Ningbo CFS" },
      { "sequence": 2, "serviceCode": "EXPORT_CUSTOMS", "from": "Ningbo CFS", "to": "Ningbo CFS" },
      { "sequence": 3, "serviceCode": "LCL", "from": "Ningbo CFS", "to": "Vancouver CFS" },
      { "sequence": 4, "serviceCode": "BOND", "from": "Vancouver CFS", "to": "Vancouver Rail Ramp" },
      { "sequence": 5, "serviceCode": "RAIL", "from": "Vancouver", "to": "Toronto" },
      { "sequence": 6, "serviceCode": "TORONTO_WAREHOUSE", "from": "Toronto Rail Ramp", "to": "Toronto Warehouse" },
      { "sequence": 7, "serviceCode": "LTL", "from": "Toronto Warehouse", "to": "M5V 2T6" }
    ]
  }
}
```

### 5.3 标准化 Supplier Quote

```json
{
  "data": {
    "id": "sq_...",
    "revision": 2,
    "status": "VALIDATED",
    "currency": "CAD",
    "totalAmount": "1840.0000",
    "transitTimeHours": 72,
    "freeTimeHours": 48,
    "validUntil": "2026-07-31T23:59:59Z",
    "items": [
      {
        "rfqItemId": "ri_...",
        "amount": "1840.0000",
        "charges": [
          { "code": "BASE", "type": "BASE", "amount": "1500.0000" },
          { "code": "THC", "type": "THC", "amount": "250.0000" },
          { "code": "DOC", "type": "DOC", "amount": "90.0000" }
        ]
      }
    ],
    "lineage": {
      "sourceAssetId": "file_...",
      "parseRunId": "parse_...",
      "aiRunId": "airun_..."
    }
  }
}
```

### 5.4 Customer Quote Comparison

```json
{
  "data": {
    "quoteId": "cq_...",
    "currency": "CAD",
    "validUntil": "2026-07-25T12:00:00Z",
    "options": [
      {
        "id": "opt_lowest",
        "type": "LOWEST_PRICE",
        "sellAmount": "5680.0000",
        "estimatedTransitHours": 480,
        "isRecommended": false,
        "riskFlags": []
      },
      {
        "id": "opt_recommended",
        "type": "RECOMMENDED",
        "sellAmount": "5920.0000",
        "estimatedTransitHours": 408,
        "isRecommended": true,
        "recommendationReasons": ["BETTER_SUPPLIER_RELIABILITY", "PRICE_WITHIN_P50_RANGE"]
      }
    ]
  }
}
```

## 6. Webhook 合约

Outbound headers：

```text
X-CLM-Event-Id: <outbox event uuid>
X-CLM-Event-Type: FulfillmentTaskStatusChanged.v1
X-CLM-Timestamp: 1784268800
X-CLM-Signature: v1=<hex hmac-sha256>
Idempotency-Key: <delivery idempotency key>
```

签名输入为 `timestamp + "." + rawBody`。接收方应在恒定时间内比较签名、限制时间偏差并按 Event ID 去重。平台只向 HTTPS 端点投递，超时短、指数退避、有最大次数和 Dead Letter；旧签名密钥在轮换宽限期内可同时验证。

Inbound Tracking/RFQ reply Webhook 同样先验签、限制 body 大小、病毒扫描附件，然后写 Inbox/原始 Asset；外部 payload 不直接改变领域状态。

## 7. 限流与配额

| Surface | 初始策略 |
| --- | --- |
| Login/Refresh | 按 IP + account；失败递增退避 |
| 普通用户 API | 按 actor + org；读写分别计数 |
| Supplier API/Webhook | 按 connection/client；突发桶 + 日配额 |
| File Upload | 限类型、单文件大小、组织总配额；完成前不可供业务使用 |
| AI Generation/Parse | 按组织/目的限并发与日预算；高优先级业务队列独立 |
| Forecast Training | 仅内部 Job；与在线推理资源隔离 |

限流信息通过 `RateLimit-*` 响应头和 `Retry-After` 返回。限流计数可在 Redis，配额/用量事实定期落库。

## 8. GraphQL 预留方式

MVP 不实现 GraphQL。预留通过以下结构完成：

- Controller 只适配 Application Command/Query，不承载业务规则。
- DTO、错误码和分页模型独立于 HTTP framework。
- Entity ID 稳定，不用数据库自增 ID。
- Reporting 查询通过 query facade/read model，未来 GraphQL Resolver 可复用。
- 任何 GraphQL 写入仍调用同一 Command、授权、幂等和审计链路。
