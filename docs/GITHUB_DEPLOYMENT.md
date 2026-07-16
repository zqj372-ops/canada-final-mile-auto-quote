# GitHub 自动部署

生产部署已经接入 `.github/workflows/ci.yml`。

## 触发方式

- 推送到 `main` 或 `codex/hermes-learning-checkpoint-20260707`：先运行完整 CI，CI 通过后自动部署生产服务器。
- 在 GitHub Actions 手动运行 `CI` workflow：可从指定分支手动部署。
- 如果测试、数据库迁移或前端构建失败，部署 job 不会执行。

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

同步时会保留服务器上的 `.env.prod`、Postgres 数据卷、`outputs/` 和私有地址资料。部署完成后会检查 API 本机健康接口和公网 `/api/health`。
