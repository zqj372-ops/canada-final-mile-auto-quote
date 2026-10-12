# GitHub 自动部署

生产部署已经接入 `.github/workflows/ci.yml`。服务器不需要保存 GitHub
账号或 Personal Access Token；GitHub Actions 在 CI 通过后经 SSH 同步已检出的确切提交。

```text
git push
-> Python 测试 + Postgres 迁移及并发验证 + Web 构建与状态机测试
-> SSH/rsync 同步代码
-> Docker Compose 重建 API 与 Web
-> 内网及公网健康检查
-> 记录线上 commit SHA
```

## 触发方式

- 推送到 `main`：先运行完整 CI，CI 通过后自动部署生产服务器。
- 当前过渡期也允许 `codex/hermes-learning-checkpoint-20260707` 自动部署；该分支合并后应以 `main` 作为唯一生产分支。
- 在 GitHub Actions 手动运行 `CI & Deploy` workflow：可从指定分支手动部署。
- 如果测试、数据库迁移或前端构建失败，部署 job 不会执行。
- 同一时间只执行一个生产部署；新提交会排队，不会中途取消正在运行的同步或容器重建。

## GitHub Secrets

仓库需要配置以下两个 Secrets：

```text
DEPLOY_SSH_KEY       # Oracle 生产机 opc 用户的私钥
DEPLOY_JUMP_SSH_KEY  # 跳板机 tk-server 的 ubuntu 用户私钥
```

私钥只保存到 GitHub Secrets，不要写进仓库。使用 GitHub CLI 配置时可以直接从本机私钥文件读取：

```bash
gh secret set DEPLOY_SSH_KEY --repo zqj372-ops/canada-final-mile-auto-quote < ~/.ssh/oci-150.230.208.231.key
gh secret set DEPLOY_JUMP_SSH_KEY --repo zqj372-ops/canada-final-mile-auto-quote < ~/.ssh/TkKey.pem
```

部署 job 使用 GitHub `production` Environment，并在 Actions 页面关联线上地址
`https://quote.freightclaw.net`。如需部署审批、分支限制或等待时间，可直接在该
Environment 的 protection rules 中配置，不需要修改服务器脚本。

## 部署内容

Actions 通过跳板机连接 Oracle 服务器，将仓库同步到：

```text
/home/opc/canada-final-mile-auto-quote
```

随后执行：

```bash
sudo -n docker compose \
  -p canada_quote_oracle \
  --env-file .env.prod \
  -f infra/docker-compose.prod.yml \
  up -d --build api web
```

同步时会保留服务器上的 `.env.prod`、Postgres 数据卷、`outputs/`、私有地址资料和
`.deploy-state/`。部署完成后会检查 API 本机健康接口和公网 `/api/health`，两者都
通过后才把线上版本记录到：

```text
/home/opc/canada-final-mile-auto-quote/.deploy-state/current-sha
/home/opc/canada-final-mile-auto-quote/.deploy-state/current-ref
/home/opc/canada-final-mile-auto-quote/.deploy-state/deployed-at
```

## 日常使用

正常发布只需要把通过评审的修改推送到生产分支：

```bash
git push origin main
```

在仓库的 **Actions → CI & Deploy** 可以查看测试、构建、部署和健康检查结果。
需要回退时，对问题提交执行 `git revert` 并推送；回退提交会走同一套 CI 和自动部署，
不要在服务器上手工覆盖代码。

## 报价工作台发布注意事项

生产库同时由独立的 `freightclaw-quote-api` 服务使用。该服务已经应用
`0024_add_m2m_quote_records`；此迁移从其运行镜像核对恢复，内容 SHA-256 为
`868770aadc59d886b5293d97542fd3a26573e11c414ff489bb2a3bf10d90ac8a`。
工作台的唯一索引迁移为 `0025_learning_candidate_idempotency`，接在 0024 后面。
不得通过重新 stamp 到 0023 绕过已存在的生产表，也不得删除 M2M 表及字段。
普通工作台、人工单、诊断历史和学习候选只处理 `scope_kind=legacy` 的记录；
学习还需满足 `learning_eligible=true`。独立 M2M 服务不在本次 Compose 重建范围内。

本次上线前需在服务器 `.deploy-state/backups/` 保留数据库 `pg_dump -Fc`、
配置、旧源码与镜像 ID，并检查备份目录权限及 `pg_restore --list` 可读性。
新增索引不会删除历史数据；旧镜像回退时保留这个索引即可，无需降级 M2M 迁移。

服务器 `.env.prod` 设置 `HERMES_CONTEXT_WORKER_ENABLED=true` 后，API 后台线程
会补齐新入队诊断上下文，不会发起模型请求或发布学习价格。
解析凭据默认使用既有 `AUTH_TOKEN_SECRET` 签名；多实例应共享同一个签名密钥。
旧学习规则缺少完整条件、来源或有效期时不再自动复用，需人工重新审核。

发布验证除内外网健康接口外，还需核对运行中的代码哈希、迁移版本、前端资源、
后台线程及受保护接口鉴权。CI 的 `TEST_POSTGRES_URL` 仅指向临时 PostgreSQL；
并发测试创建独立 schema 并在结束时移除，禁止将该变量指向生产库。
