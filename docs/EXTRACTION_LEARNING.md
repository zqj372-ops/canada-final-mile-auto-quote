# 解析优化与人工纠错闭环

日期：2026-10-12。实现复用现有审计、人工任务、候选和规则，没有新增业务表或独立页面。

## 已实现的行为

- 标签完整、单位明确的单票走本地解析；复杂文本沿用现有模型，默认仍是货物/地址双路解析。
- 尾板、手叉车、预约为 true / false / null。未提及、互相矛盾或提问时保持未知，不默认“不需要”。
- 模型 HTTP 连接按地址、凭据指纹和超时隔离复用，最多 16 个 client、每个最多 8 个连接。
- 解析任务共用 8 个 worker，最多 16 个在途/排队任务。默认模型解析预算 30 秒，接口允许 1–60 秒。
  超时后返回控制权并取消未启动任务；已开始的同步网络调用不能被强制瞬间中止，受剩余网络超时、
  响应体 2 MiB 限制和分块截止检查约束。没有无限追加重试或无限线程。
- 返回 parser version、prompt/schema hash、模型配置标识、调用次数、修复次数、耗时、供应商返回的 token 数。
  缺失 token 数据保留未知；统计不记录模型密钥。
- 未改变默认模型、提示词发布策略或价格矩阵；单路策略用于有固定答案的比较。

## 从修改到样本

`/quotes/ai-extract` 返回签名 `extraction_receipt`，绑定原文、解析快照、账号、版本信息及运行 ID，有效 12 小时。
确认报价原样带回回执与快照；修改值放在 quote，逐字段原因放在 correction_reasons。
原文或快照被改动、回执过期或账号不一致时返回 422，需重新解析。
无回执的手工录入仍可报价，但纠错来源标记为未验证，不能批准为答案。

修改原因有三类：

- `extraction_error`：解析错误，可提交运营核对。
- `customer_update`：客户补充/变更，不能把新信息当成原文答案。
- `business_decision`：业务判断或计价调整，不作为解析标签。

没有选择原因为 unclassified；未修改也不意味着已验证正确。
已有 `/audit` 页面可核对原文、逐字段前后值及修改原因，选择通过的解析错误，填写分组和核对说明。
接口为 `PATCH /quotes/audit/{quote_id}/extraction-feedback`，仅 operator/admin 可写，使用 expected_version 防止覆盖新审核。
默认加入 test 集，界面不提供自动训练、改提示词或发布模型的按钮。

签名密钥优先读取 `EXTRACTION_RECEIPT_SECRET`，否则使用 `AUTH_TOKEN_SECRET`。
多进程/多实例必须配置同一个稳定密钥；均未配置时使用进程内随机密钥，重启会使旧回执失效。
不要将密钥写入源码。生产 Compose 已传递上述配置。

## CLI 导出与评测

在已授权、正确配置 DATABASE_URL 的环境中导出已审核样本：

```bash
python scripts/export_extraction_feedback.py --output outputs/reviewed-extraction.jsonl
```

只导出来源已验证、人工批准且原因是解析错误的字段；按解析运行 ID 去重。
导出包含客户原文，只保存在指定本地路径，不自动脱敏、上传或发送。共享或模型评测前应按实际数据权限处理。
同一客户/模板使用相同 group_id；同组或相同原文跨训练/验证/测试集时评测拒绝运行。
评测只统计有显式答案的字段，不把部分字段通过称为整票报价正确。

无需网络的合同样例检查：

```bash
python scripts/evaluate_extraction.py \
  --dataset tests/fixtures/extraction/conformance.jsonl \
  --strategies local --output outputs/extraction-evaluation-local.json
```

需要真实模型对比时，显式选择已授权的配置和调用开关：

```bash
python scripts/evaluate_extraction.py \
  --dataset outputs/reviewed-extraction.jsonl \
  --strategies local,single,dual --split test --budget-seconds 30 \
  --ai-config-id <已授权模型配置ID> --allow-model-requests \
  --output outputs/extraction-evaluation-models.json
```

此命令会把样本原文发给所选模型供应商，并可能计费；本次没有运行。
报告提供字段正确率、所有已标注字段均正确的样本比例、未知值保留率、失败数、P50/P95、调用/修复次数和 token 数。
目前没有接入供应商单价表，报告不声称已测出货币成本。

## 迁移与上线前检查

`0025_learning_candidate_idempotency` 为 v2 duplicate_key 添加部分唯一索引，旧数据及旧重复键保留。
部署时仍通过项目既有 `alembic upgrade head` 运行，不直接对未知数据库 stamp。
旧宽范围学习规则因缺少严格条件/有效期而不再自动复用，需要运营复核重新发布。

诊断 worker 开启方式及学习价格条件见 [Hermes 机制](HERMES_LEARNING.md)。
本次只在隔离本地库运行；没有生产部署、外部通知、付费模型调用、自动训练或真实价格业务验证。

## 验证与限制

- 352 项后端全量测试通过；随后证据摘要修正的 36 项相关测试再次通过。
- 8 项前端测试及 TypeScript/Vite 构建通过；桌面/手机布局检查通过，浏览器错误/警告日志为空。
- 浏览器实际完成未确认服务拦截、模拟纠错记录、审核批准，以及带来源/有效期的学习价格批准。
- 运行中 API 复用 USD 350 测试整口价；相同邮编更改街道后恢复人工处理，基础价和燃油保持未知。
- 诊断上下文由后台从 pending 补齐为 ready；CLI 导出只包含获批字段，客户补充被排除。
- 新索引在隔离 SQLite 中升级/回退/再升级成功，旧重复记录保留、新重复键被拒绝。
- 全链 SQLite 迁移受已有 0007 中 PostgreSQL NOW() 语句限制；生产 PostgreSQL 全链迁移和锁竞争未实测。
- 本机没有 Docker CLI，未运行 Compose config/容器验证；应用的本地独立进程运行验证已完成。
- 8 个 synthetic_fixture 本地合同样例通过、零模型调用。这是回归证据，不是生产准确率。

真实询价的快路径覆盖率、模型单路/双路准确率与延迟差异，以及每条正确报价的成本，仍需真实脱敏样本和授权模型对比。
应先积累按客户/模板分组的人工审核样本，冻结验证/测试集，确认改进后再单独审核发布。
