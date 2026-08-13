# GitHub 受控部署

生产部署已经接入 `.github/workflows/ci.yml`。服务器不需要保存 GitHub
账号或 Personal Access Token；只有 `main` 分支的手动 workflow dispatch 在全部门禁通过后，才经 SSH 同步已检出的确切提交。

```text
git push
-> Python 测试 + Postgres 迁移验证 + Web 构建（不触碰生产）
手动 workflow_dispatch + 明确发布参数
-> SSH/rsync 同步代码
-> Docker Compose 迁移并启动 API/Web
-> 操作员提供发布参数并受控发布 quote manifest
-> 内网 /status + 公网 /api/status readiness readback
-> 记录线上 commit SHA
```

## 触发方式

- 推送到 `main` 或过渡分支：只运行完整 CI，不自动触碰生产。
- 生产部署必须在 GitHub Actions 手动运行 `CI & Deploy` workflow；该 workflow 要求填写规则版本、数据版本、UTC 发布时间、有效窗口和 test-data 声明。
- 如果测试、数据库迁移或前端构建失败，部署 job 不会执行。
- 缺少人工发布参数时 workflow 不会启动 production deploy；不会虚构规则、数据版本或时间。
- 同一时间只执行一个生产部署；新提交会排队，不会中途取消正在运行的同步或容器重建。

## GitHub Secrets

仓库需要配置以下两个 Secrets：

```text
DEPLOY_SSH_KEY       # Oracle 生产机 opc 用户的私钥
DEPLOY_JUMP_SSH_KEY  # 跳板机 tk-server 的 ubuntu 用户私钥
QUOTE_READINESS_API_KEY # 只读 readiness 回读用 X-API-Key
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

随后执行迁移并启动服务（CI 用 `DEPLOY_SHA` 同时绑定 `QUOTE_RELEASE_ID`）：

```bash
sudo -n docker compose \
  -p canada_quote_oracle \
  --env-file .env.prod \
  -f infra/docker-compose.prod.yml \
  up -d --build api web
```

同步时会保留服务器上的 `.env.prod`、Postgres 数据卷、`outputs/`、私有地址资料和
`.deploy-state/`。受控发布 manifest 后，CI 检查 API 本机 `/status` 和公网 `/api/status`
的 `ready`、`test_data`、`release_id` 和 snapshot hash；两者都通过后才把线上版本记录到：

```text
/home/opc/canada-final-mile-auto-quote/.deploy-state/current-sha
/home/opc/canada-final-mile-auto-quote/.deploy-state/deployed-at
```

## 日常使用

正常发布分两步：先推送通过评审的修改触发只读 CI，再在 `main` 上手动 dispatch 生产 workflow 并填写完整发布参数：

```bash
git push origin main
```

在仓库的 **Actions → CI & Deploy** 手动选择 `main` 并填写规则版本、数据版本、UTC
发布时间、有效窗口和 `test_data=false`。参数校验、版本/提交绑定和 ref 校验均在首个
SSH/rsync/Compose 步骤之前完成；参数缺失、测试数据或非 `main` ref 会零生产副作用失败。
部署成功后线上只记录 `.deploy-state/current-sha` 和 `.deploy-state/deployed-at`。
需要回退时，对问题提交执行 `git revert`、重新跑 CI，再对 `main` 手动 dispatch；不要在服务器上手工覆盖代码。
