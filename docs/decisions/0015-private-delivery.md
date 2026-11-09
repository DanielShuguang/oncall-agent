# 0015 · 私有化交付形态：compose profile + 镜像内迁移 + 演示 seed

- 状态：已采纳（W6 D27）
- 日期：2026-11-09
- 相关：[docs/09-deploy-private.md](../09-deploy-private.md)、[docs/10-roadmap-6weeks.md](../10-roadmap-6weeks.md)

## 背景

W1–W5 的开发方式是「本机 postgres/redis + `make api` + `make web`」。
W6 要求「陌生人按 README 30 分钟内跑起来」，同时不能破坏日常开发体验：
`make up` 只起中间件，不应该每次都构建前端镜像。

另一个现实约束：mock 模式下知识库默认只在内存后端自动 seed；
切到 Postgres 后 `rag/service.py` 明确不自动灌数据，避免生产被演示数据污染。
但演示环境如果库是空的，第一条「VPN 连不上怎么办」就会拒答，交付第一印象直接失败。

## 决策

### 1. 单 compose 文件 + `full` profile

`docker-compose.yml` 保留 postgres/redis 为默认服务；`api`/`web` 放进 `profiles: ["full"]`。

- 日常：`make up` 只起中间件，行为与 W1–W5 一致
- 交付：`make stack` = `docker compose --profile full up -d --build`
- 不维护两份 develop/prod compose 文件，避免配置漂移

### 2. 迁移放在 API entrypoint，单副本假设

`server/docker-entrypoint.sh` 顺序执行：

1. `alembic upgrade head`
2. `ONCALL_SEED_DEMO=true` 时 `python -m app.seed.generate --db`
3. `exec uvicorn ...`

理由：演示/单机部署只需要一条命令，不需要用户记得先跑迁移。
代价：**多副本滚动升级时多个容器会同时跑迁移**。当前明确只支持单 API 副本；
多副本应把迁移拆成独立 job，再滚动 api（见「后续」）。

### 3. 演示 seed 用显式开关，不靠后端自动灌

`ONCALL_SEED_DEMO` 默认 `false`（代码层），两个 compose 文件显式设为 `true`（演示优先）。
生产设 `false`，避免每次重启把 seed 语料 upsert 回知识库。

seed 本身按 `source` upsert，重复执行是幂等的；但「幂等」不等于「应该在生产跑」。

### 4. Web 用 Nginx，SSE 关闭缓冲

`web/Dockerfile` 两阶段：Node 构建 → Nginx 托管。`web/nginx.conf`：

- `proxy_buffering off` / `proxy_cache off`：否则 SSE 事件被 Nginx 攒着一起发
- `proxy_read_timeout 3600s`：长对话不被 60s 默认超时切断
- `resolver 127.0.0.11` + 变量 upstream：api 容器重建后重新解析 IP，避免缓存旧地址
- `try_files ... /index.html`：刷新 `/console/kb` 不 404

### 5. 离线交付用 `docker save` + 独立 compose 文件

`make images` 导出四张镜像；`docker-compose.offline.yml` 不含 `build`，
应用镜像 `pull_policy: never`，确保客户内网不会尝试联网拉取。

暂不做 multi-arch/信创镜像：W6 只交付 x86_64，ARM64 与国产卡在 docs/09 §6 标注为待验证。

### 6. 压测只承诺口径，不承诺开发机数字

`app/eval/loadtest.py` 打完整 SSE run，成功只认 `run.completed`。
报告强制写明环境；README 明确「开发机 16 vCPU/15GiB，不是 8C16G 验收」。
8C16G 目标（并发 ≥20、事件 ≥200 条/s）需要同规格机器重跑，不能用开发机数字替代。

## 后果

- 好：一条命令可演示；开发/交付共用一份 compose；SSE 在 Nginx 下实测可用
- 好：生产不会被 seed 污染（显式开关）；离线包不依赖外网
- 代价：单副本迁移假设；镜像构建需要网络拉 Node/Python 基础镜像；
  没有镜像签名/SBOM，交付安全清单仍需补齐
- 未验证：多副本、ARM64、8C16G 容量、真实模型（mock 只验证链路）

## 后续

1. 多副本：迁移拆成 `migrate` job，entrypoint 只启动 uvicorn
2. 镜像：固定 digest、生成 SBOM、加 `cosign` 签名
3. 容量：在 8C16G 上跑 `make loadtest`，把 CPU/内存/Postgres 版本写进报告
4. 信创：ARM64 multi-arch + 达梦/金仓方言评估（docs/09 §6）
