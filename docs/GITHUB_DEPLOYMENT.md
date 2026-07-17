# GitHub 自动部署

生产部署已经接入 `.github/workflows/ci.yml`。服务器不需要保存 GitHub
账号或 Personal Access Token；GitHub Actions 在 CI 通过后经 SSH 同步已检出的确切提交。

```text
git push
-> Python 测试 + Postgres 迁移验证 + Web 构建
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
