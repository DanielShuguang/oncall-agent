# 09 · 私有化部署

> 长沙的客户（制造业、医疗、政企）最在意的不是模型多强，是**数据不出内网、能装上、出问题有人兜**。

## 1. 三种部署形态

| 形态 | 资源 | 适用 | 模型 |
|---|---|---|---|
| 演示版 | 8C16G | 面试演示、POC | 云 API 或 Ollama 7B |
| 标准私有化 | 16C32G | 中型企业 | 本地 vLLM 7B/14B 量化 |
| 离线信创 | 32C64G + 国产卡 | 政企 | 适配后的国产模型 |

## 2. 组件清单

| 组件 | 必需 | 说明 |
|---|---|---|
| PostgreSQL 16 + pgvector | ✅ | 业务 + 向量 + 事件 |
| Redis 7 | ✅ | 限流、预算、锁 |
| api（FastAPI） | ✅ | 无状态，可多副本 |
| web（静态资源） | ✅ | Nginx 托管 |
| 模型服务 | ✅ | 云 API / Ollama / vLLM 三选一 |
| Langfuse | ⭕ | 可选，替代方案是自研看板 |

## 3. 一键起

```bash
cp .env.example .env        # 至少确认 MOCK_MODE / SESSION_SECRET；不填模型 key 也能演示
docker compose --profile full up -d --build
# 打开 http://<host>:8080
docker compose --profile full ps
docker compose --profile full logs -f api
```

`api` / `web` 放在 compose 的 `full` profile 里：日常 `make up` 只起 postgres + redis，
不会每次都 build 前端；交付/演示用 `make stack`（等价于上面的 `--profile full up --build`）。

容器启动顺序由 entrypoint 保证：`alembic upgrade head` →（`ONCALL_SEED_DEMO=true` 时）
灌 50 篇知识库 / 200 资产 / 500 工单 → uvicorn。演示环境默认灌数据；
**生产必须设 `ONCALL_SEED_DEMO=false`**，否则每次重启都会把 seed 语料 upsert 回知识库。

| 项 | 默认 | 说明 |
|---|---|---|
| Web | `http://<host>:8080` | Nginx 托管静态资源并反代 `/api`，SSE 已关闭缓冲 |
| API | `http://127.0.0.1:8000` | 只绑定本机，供调试/压测；生产只暴露 8080 |
| 健康检查 | `GET /api/health` | 返回 db/redis 状态；容器 healthcheck 也用它 |
| 数据 | named volume `oncall-pgdata` / `oncall-redisdata` | `docker compose down -v` 会清空 |

> 真实本地模型跑在宿主机时，容器内用
> `ONCALL_LOCAL_BASE_URL=http://host.docker.internal:11434/v1`（compose 已加
> `host.docker.internal:host-gateway`）。Linux 宿主机同样适用。

## 4. 离线镜像

```bash
# 有网机器：构建并导出（Makefile 目标等价于 docker save 四条镜像）
make stack
make images          # -> oncall-images.tar

# 客户内网
docker load -i oncall-images.tar
cp .env.example .env
# 生产：ONCALL_ENV=prod、强 SESSION_SECRET、ONCALL_SEED_DEMO=false
docker compose -f docker-compose.offline.yml up -d
```

`docker-compose.offline.yml` 不包含 `build`，所有服务用本地镜像并设 `pull_policy: never`；
镜像清单：

```
oncall-api:latest
oncall-web:latest
pgvector/pgvector:pg16
redis:7-alpine
```

配套交付物：

```
delivery/
├─ oncall-images.tar
├─ docker-compose.offline.yml
├─ .env.template          # 从 .env.example 改：ONCALL_ENV=prod + 强 SESSION_SECRET
├─ 部署手册.pdf
└─ 验收清单.xlsx
```

## 5. Mock 模式（演示的命门）

```env
ONCALL_MOCK_MODE=true
```

行为：

- **不构建模型网关**：classify/plan 走确定性规则，`model_calls` 为空、成本恒为 0
- 工具照常执行：资产/工单来自内存仓储或 Postgres 里 seed 落的表，不连真实 CMDB/工单系统
- 事件流、审批、回放全部照常执行
- 切真实模型：`ONCALL_MOCK_MODE=false`，再按 §5.1 配 provider

### 5.1 真实模型

```env
ONCALL_MOCK_MODE=false
# 云端（OpenAI 兼容）
ONCALL_CLOUD_BASE_URL=https://api.example.com/v1
ONCALL_CLOUD_API_KEY=...
ONCALL_CLOUD_MODEL=gpt-4o-mini
ONCALL_CLOUD_PRICE_IN_CENTS_PER_1M=15
ONCALL_CLOUD_PRICE_OUT_CENTS_PER_1M=60
# 本地（Ollama 原生接口；base_url 配 /v1 也能用）
ONCALL_LOCAL_BASE_URL=http://127.0.0.1:11434
ONCALL_LOCAL_MODEL=qwen2.5:7b
# 预算与限流（单位：分 / 元 / 次）
ONCALL_RUN_BUDGET_CENTS=50
ONCALL_DAILY_BUDGET_CNY=5
ONCALL_USER_DAILY_BUDGET_CNY=0
ONCALL_RATE_LIMIT_PER_MIN=30
```

> 价格单位是「分 / 百万 token」，不是美元；填错会直接体现在成本看板上。
> `ONCALL_USER_DAILY_BUDGET_CNY=0` 表示默认不给每个用户设上限；**无论默认值是多少**，
> 都可以在成本页按用户单独覆盖（覆盖里的 0 = 该用户不限）。
> 预算账本与成本看板口径不同：成本页的「今日已用」读账本（含未结算预扣），超过 300 秒
> 仍未结算的预扣会标红；实际花费仍看成本汇总（`model_calls`，ADR-0028）。
> 详见 [ADR-0013](decisions/0013-model-gateway.md)、[ADR-0026](decisions/0026-user-daily-budget.md)、
> [ADR-0028](decisions/0028-budget-observability.md)。

> 目的：面试官/客户拿到仓库，`docker compose up` 就能看到完整链路，不需要 key、不需要联网。这是开源项目的第一印象分。

## 6. 信创适配说明（写文档就够，别真去适配）

| 项 | 现状 | 说明 |
|---|---|---|
| 操作系统 | 待验证 | 麒麟 V10 / 统信 UOS；容器化后主要依赖内核版本与 cgroup v2 |
| CPU | 待验证 | 鲲鹏/飞腾（ARM64）；镜像需 multi-arch |
| 数据库 | 可替换 | 达梦/人大金仓；需替换 SQLAlchemy 方言，pgvector 不可用 → 换 Qdrant |
| 模型 | 可替换 | 国产模型需 OpenAI 兼容网关 |
| 浏览器 | 已兼容 | 政企常配 Chrome 90+，注意别用太新的 CSS |

> 这一节的价值：**证明你知道信创的门槛在哪**，而不是假装能一键适配。面试时说"容器化后主要是内核与架构问题，数据库方言和向量库是真正的替换点"，比说"我们支持信创"可信。

## 7. 资源与容量

| 项 | 单机 8C16G 验收目标 |
|---|---|
| 并发对话 | ≥ 20 |
| 检索 QPS | ≥ 30（5 万 chunk） |
| 事件写入 | ≥ 200 条/s |
| 冷启动 | ≤ 30s |

压测脚本：`server/app/eval/loadtest.py`（W6 D27）：

```bash
# 先起 API（本地 make api 或容器 make stack）
make loadtest
# 等价于：
# cd server && uv run python -m app.eval.loadtest --requests 100 --concurrency 20 --users 20
```

口径：每个请求是一次完整 SSE run（建 run → 8 节点 → 事件落库 → `run.completed`），
成功只认 `run.completed`；默认多用户 token 规避单用户 30 次/分钟限流。
报告写到 `server/eval-reports/load-*.md`（gitignore），README 只贴**同环境同参数**的结果。

当前开发机结果（2026-11-09，Windows 11 + WSL2 **16 vCPU / 15GiB**，Docker 29.1.3，
单 API 容器 + Postgres/Redis 容器，mock 模式，100 请求 / 20 并发 / 20 用户）：
成功率 100%、12.60 run/s、306.6 事件/s、p95 端到端 1814ms、p95 首事件 238ms。

> 这不是 8C16G 生产容量验收。8C16G 目标（并发 ≥20、检索 QPS ≥30、事件 ≥200 条/s、
> 冷启动 ≤30s）必须在同规格机器上用同一脚本重跑；开发机数字只证明链路没堵。

## 8. 运维

| 场景 | 方案 |
|---|---|
| 日志 | 结构化 JSON → 文件；可选 Loki |
| 指标 | `/metrics`（Prometheus 格式），至少暴露：run 数、失败率、p95、token 消耗 |
| 备份 | `pg_dump` 每日 + 事件表按月归档 |
| 孤儿 run | 后台默认每 60s（`ONCALL_RECOVERY_INTERVAL_S`）扫描；超过 `ONCALL_STALE_RUN_MIN`（默认 10 分钟）没有事件的 `running` run 追加 `run.failed(RUN_INTERRUPTED)`。立即处理先看候选：`cd server && uv run python -m app.cli reap --dry-run`（容器内 `docker compose exec api python -m app.cli reap --dry-run`），确认后 `make reap`。只收敛状态，不自动重试写工具（[ADR-0017](decisions/0017-stale-run-recovery.md)） |
| 保留清理 | 后台默认每 6 小时（`ONCALL_RETENTION_INTERVAL_S`）清理超过 180 天的数据：`ONCALL_EVENT_RETENTION_DAYS` 的 run 事件（按 run 整场删除并写 `runs.events_pruned_at`）、`ONCALL_RUN_CONTENT_RETENTION_DAYS` 的正文（清空 `runs.input/output` 与引用快照 `runs.citations` 并写 `content_pruned_at`，只留摘要/计量/失败归因）与已决议审批的快照（清空 `approvals.state`，参数/理由/决议人保留）、`ONCALL_MODEL_CALL_RETENTION_DAYS` 的计量明细，以及 `approval_grants` 里已过期的会话授权（过期即删）；每轮最多 `ONCALL_RETENTION_MAX_BATCHES`（默认 10）批 × `ONCALL_RETENTION_BATCH`（默认 200）行；按 1–2 条计量/run 估算约 4000–8000 run/天，跑量更大要调这两个值；跑满上限时日志出现 `retention_backlog_remaining` 表示在追赶。**清理是不可逆的**，现场要留更久只能调大保留天数；若把事件保留期调到 180 天以上，
必须同时把正文保留期调到不短于它，否则启动失败（错误信息会说明两种改法）。立即处理或先看候选：`cd server && uv run python -m app.cli prune --dry-run`（输出含 `content_before` / `content_runs` / `approval_snapshots` / `approval_grants`），确认后 `make prune`（[ADR-0021](decisions/0021-data-retention.md)、[ADR-0023](decisions/0023-run-content-retention.md)、[ADR-0027](decisions/0027-approval-snapshot-retention.md)） |
| 历史引用回填 | ADR-0031 之前写入的 run 没有 `runs.citations` 快照；事件与正文都还在时可用 `make backfill-citations`（或 `python -m app.cli backfill-citations --dry-run`）从最后一条 `message.completed` 重建。默认扫描 100 场（`--limit`），可重复执行，写过的不再入选；事件/正文已过保留期的 run 跳过。回填不改变可见性：详情仍按当前权限与正文保留期过滤（[ADR-0042](decisions/0042-citation-backfill.md)） |
| 升级 | 先跑 alembic 迁移 → 再滚动重启 api |
| 回滚 | 镜像 tag + 数据库迁移的 downgrade 脚本（每次迁移必须写 downgrade） |

## 9. 安全清单

- [ ] 所有对外接口鉴权，管理接口二次校验角色
- [ ] 工具白名单默认拒绝（未注册即拒）
- [ ] 身份字段不允许来自模型入参
- [ ] 上传文件类型与大小限制；PDF 解析在 `spawn` 子进程（60 秒超时，崩溃/超时返回 422），不阻塞 API 事件循环（ADR-0032）
- [ ] 提示词注入防护：检索内容包 `<document>` 并声明非指令
- [ ] 审计日志保留 180 天（清理任务默认 180 天；调小 `ONCALL_EVENT_RETENTION_DAYS` 前确认合规要求，ADR-0021）
- [ ] 问答正文保留期符合隐私要求（默认 180 天，`ONCALL_RUN_CONTENT_RETENTION_DAYS` 不得小于事件保留期；调小要连同事件一起调，ADR-0023）
- [ ] 审批快照随正文保留期清空、决议证据永久保留；过期会话授权由清理任务删除（ADR-0027）
- [ ] 预算账本读取失败时管理页返回 503，而不是显示成「今天没花钱」；预扣泄漏能在成本页看到笔数与金额（ADR-0028）
- [ ] `.env` 不入库，密钥不出现在日志
- [ ] 依赖漏洞扫描（`uv pip audit` / `pnpm audit`）

## 10. 验收清单（交付用）

- [ ] `docker compose up` 后 3 分钟内可访问
- [ ] mock 模式可完整演示三条剧本
- [ ] 断网 10s 恢复不丢消息
- [ ] 越权用例 100% 拦截
- [ ] 成本看板数据与 `model_calls` 一致
- [ ] 成本页个人预算的「今日已用」与账本一致；预扣泄漏能看到笔数与金额（ADR-0028）
- [ ] 备份恢复演练通过
