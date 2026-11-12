# OnCall

**私有化企业智能体工作台** —— 查资产 → 验权限 → 调工具 → 开单 → 审批 → 回填，全链路可控、可审计、可计量。

面向企业 IT 服务台 / 售后工单场景：Agent 可以直接查 CMDB、检索知识库、调用诊断工具、生成工单，但**任何写操作都必须经过人工审批**，每一次对话都能算清 token 成本与引用来源。

> 这个项目同时是一份求职作品：用真实的工程取舍回答"你如何让 Agent 在生产环境里可控"。

---

## 为什么是它

| 问题 | 常见做法 | 本项目做法 |
|---|---|---|
| 模型能不能直接写库？ | 能，Demo 里很常见 | 不能。权限、写库、金额、审批全部由业务代码判定，模型只产出意图与参数 |
| 工具调用失败怎么办？ | 加重试 | 按错误类型决定是否重试 + 指数退避 + 抖动 + 业务降级 |
| 回答错了怎么查？ | 看日志 | 每个答案带原文引用；运行可按事件完整回放（事件默认保留 180 天）；引用文档收权后旧回答不再展示 |
| 花了多少钱？ | 月底看账单 | 单次对话实时计量，按 run / 天 / 模型聚合 |
| 能不能私有化？ | 依赖云 API | 本地模型（vLLM / Ollama）+ docker-compose 一键部署；资源目标 8C16G，当前只完成开发机链路验证 |

## 核心能力

1. **RAG 知识库**：混合检索（BM25 + 向量 + RRF）+ rerank + 引用溯源（可跳全文）+ 文档级可见范围（公开 / 指定角色，召回前过滤）+ 无命中兜底
2. **工具层**：统一 `ToolSpec` 注册 + 治理；传输可替换（当前进程内调用，MCP/HTTP 传输未接）
3. **Agent 运行时**：显式 8 节点状态机（LangGraph 可选），只有 2 个节点调 LLM（规则优先）；多轮上下文由服务端按会话注入（3 轮，追问自动拼最近几轮的检索词），客户端不传历史
4. **工具治理**：白名单、会话级权限、单工具超时、错误分类重试、业务降级、保留字段拒绝
5. **人工审批**：写操作必须确认，支持"本会话内允许"
6. **模型网关**：多模型接入、规则路由、限流、每日预算（全局 + 按用户）、成本埋点
7. **可观测与保留**：事件落库、断线续跑、按 run 回放、成本与质量看板；事件/计量/问答正文按保留期清理（默认 180 天），run 摘要保留；回答内容按**当前**文档可见性回收，撤权立即生效
8. **私有化交付**：docker-compose + 离线镜像 + mock 模式（不填模型 key 也能演示）

## 架构

```
企业微信 / Web 门户
        │  SSE
┌───────▼────────────────────────────────────┐
│  Web 前端（React 19 + TS + Tailwind CSS）     │
│  对话流 / 工具卡片 / 工单卡 / 审批 / 成本看板   │
└───────┬────────────────────────────────────┘
        │  HTTP + SSE
┌───────▼────────────────────────────────────┐
│  FastAPI 网关                                 │
│  鉴权 / 会话 / 限流 / 预算 / 事件落库          │
└───┬──────────────┬──────────────┬───────────┘
    │              │              │
┌───▼────┐   ┌─────▼──────┐  ┌────▼─────────┐
│显式状态机│   │ 模型网关     │  │ 工具运行时     │
│ 状态机  │   │ 路由/降级/成本│  │ 工具注册 + 治理│
└───┬────┘   └─────┬──────┘  └────┬─────────┘
    │              │              │
┌───▼──────────────▼──────────────▼───────────┐
│ Postgres(+pgvector) / Redis / 事件表          │
│ CMDB · 工单系统 · 知识库（可对接或模拟）        │
└──────────────────────────────────────────────┘
```

详细设计见 [docs/01-architecture.md](docs/01-architecture.md)。

## 快速开始

### 方式 A：整栈容器（第一次跑推荐）

```bash
cp .env.example .env
docker compose --profile full up -d --build
# 打开 http://127.0.0.1:8080
```

首次启动会执行迁移并灌演示数据（50 篇知识库 / 200 资产 / 500 工单），
无需模型 key：默认 `ONCALL_MOCK_MODE=true`，规则引擎 + 确定性哈希检索也能跑完三条剧本。
健康检查 `curl http://127.0.0.1:8000/api/health`；停止用
`docker compose --profile full down`（清数据加 `-v`）。

> 生产/客户环境必须改 `ONCALL_SESSION_SECRET`、设 `ONCALL_ENV=prod` 与
> `ONCALL_SEED_DEMO=false`，详见 [docs/09-deploy-private.md](docs/09-deploy-private.md)。

### 方式 B：本地开发

##### 0. 前置

- Docker Desktop（含 Compose）
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 20+ + pnpm

#### 1. 起中间件```bash
cp .env.example .env
docker compose up -d          # postgres:16 + pgvector, redis:7
```

#### 2. 起后端

```bash
cd server
uv sync --extra rag        # rag = pypdf + python-docx；不装则只能上传 MD/TXT
uv run alembic upgrade head
uv run python -m app.seed.generate --db   # 50 篇知识库 / 200 资产 / 500 工单
uv run uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000/docs
```

> `seed --db` 需要 Postgres 已启动（第 1 步）且迁移已执行；只想看生成的文件可省略 `--db`。
> 默认 embedding 是确定性哈希（无模型依赖）；接 bge-m3 见 `.env.example` 的 `ONCALL_EMBEDDING_*`。

#### 3. 签发本地 token

v1 不接 SSO，除 `/api/health` 与 OpenAPI 文档外，业务接口都要求 Bearer token（见 [docs/11](docs/11-dev-setup.md) §2.1）。仍在 `server/` 目录执行：

```bash
uv run python -m app.cli token --user u_102 --roles employee
# 复制输出，粘到前端右上角「设置 Token」

# 管理知识库时需要 admin 角色
uv run python -m app.cli token --user admin_1 --roles admin

# 审批写操作需要 approver 角色（不能用发起人自己的 token 自批）
uv run python -m app.cli token --user u_900 --roles approver
```

> 演示审批：用员工 token 发「帮我开一张报修工单」→ 页面出现审批卡 →
> 换 approver token 在 `POST /api/approvals/{id}/resolve` 提交批准（或直接调接口）。
> 前端审批卡按钮走当前 token，所以审批人要用 approver token 登录。

#### 4. 起前端

```bash
cd web
pnpm install
pnpm dev
# 打开 http://127.0.0.1:5173
```

前端已配置 `/api` 代理到 `http://127.0.0.1:8000`。

> `/api/chat/stream` 已由真实运行时驱动：8 节点状态机 → 混合检索（pgvector + tsvector）→
> `query_cmdb`（走治理层）→ 带引用的回答。写操作会挂起成审批卡，批准后从快照恢复执行
> 并真正落工单。三条剧本：打印机离线 / 申请 VPN 权限（含审批）/ VPN 知识问答。

## 目录

```
oncall/
├─ docs/          # 设计文档（先读 00-index.md）
├─ server/        # FastAPI + LangGraph
└─ web/           # React 19 + Vite + Tailwind CSS
```

## 文档

| 文档 | 内容 |
|---|---|
| [00-index](docs/00-index.md) | 文档索引与阅读顺序 |
| [01-architecture](docs/01-architecture.md) | 系统架构、模块职责、核心时序 |
| [02-data-model](docs/02-data-model.md) | 数据表设计、事件模型、索引 |
| [03-api-contract](docs/03-api-contract.md) | REST 接口 + SSE 事件协议 |
| [04-agent-design](docs/04-agent-design.md) | 8 节点状态机、规则优先策略 |
| [05-rag-design](docs/05-rag-design.md) | 解析、切分、混合检索、引用 |
| [06-tool-governance](docs/06-tool-governance.md) | 工具协议、白名单、权限、超时、审批 |
| [07-frontend-design](docs/07-frontend-design.md) | 路由、状态机、组件、交互 |
| [08-eval-metrics](docs/08-eval-metrics.md) | 评测集与指标口径 |
| [09-deploy-private](docs/09-deploy-private.md) | 私有化、离线镜像、信创 |
| [10-roadmap-6weeks](docs/10-roadmap-6weeks.md) | 30 天逐日计划与验收 |
| [11-dev-setup](docs/11-dev-setup.md) | 环境搭建与排错 |

> 用 AI 编码助手改这个仓库时，先让它读 [AGENTS.md](AGENTS.md)——那是约束清单（硬规则、recipe、反模式），不是背景介绍。

## 状态

| 模块 | 状态 | 验证方式 |
|---|---|---|
| 文档（12 篇 + 38 篇 ADR + 评测基线） | ✅ 完成 | — |
| 前端骨架（状态机 / SSE 客户端 / 页面 / 审批卡 / 运行回放 / 成本页） | ✅ 可用 | `tsc --noEmit`、`oxlint 0`、`oxfmt --check` 通过；`vitest` 65/65；`pnpm build` 成功 |
| 后端骨架（事件契约 / SSE / 健康检查） | ✅ 可运行 | 默认 `pytest` **457 passed + 34 skipped**；设 `ONCALL_TEST_DATABASE_URL`（指向一个可清空的库）后 **488 passed + 3 skipped**，再加 `ONCALL_TEST_REDIS_URL` 为 **491 passed**（含并发 seq、pgvector 检索、可见性矩阵、会话历史隔离、审批并发与事务回滚、孤儿回收并发、保留清理契约与审批快照、引用快照与内容回收、个人预算与账本快照、工单自助查询、工单详情、会话列表与分页、资产查询接表、运行过程回放、批量会话详情、工具配置变更历史、计量一致性） |
| 本地 JWT（W1 D2） | ✅ 已完成 | `tests/test_auth.py` 20 条：签发/验签、过期、alg=none、401 JSON、OpenAPI Bearer、run 归属隔离 |
| 事件落库 + 断线续传（D4） | ✅ 已完成 | `alembic upgrade head` + `alembic check` 无漂移；`tests/test_store_contract.py`（内存 + Postgres 契约）、`tests/test_chat_stream.py`（落库、幂等回放、503 语义） |
| 最小 Agent 运行时（W1 D5） | ✅ 已完成 | `tests/test_agent_runtime.py` 9 条：工具真实执行、检索引用、写操作挂起审批、工具失败降级、步数/时长上限 |
| RAG 全链路（W2 D6–D10） | ✅ 已完成 | 50 篇 seed 知识库（含过期版本/冲突/噪声）；解析→切分→pgvector+tsvector→RRF→阈值→引用；`tests/test_rag_parse.py`、`test_rag_retrieve.py`、`test_rag_pg.py`、`test_kb_api.py`；评测基线 [docs/eval/baseline-v1](docs/eval/baseline-v1.md)（50 条，recall@5 100%、cite_acc 97.1%） |
| 工具治理五道闸门 + 超时重试 | ✅ 已实现 | `tests/test_tools_guard.py` 22 条：权限/保留字段/入参白名单/enum/超时重试/身份注入/伪造身份/工单只查本人 |
| 8 节点图 + 审批闭环（W3 D11–D15） | ✅ 已完成 | `tests/test_agent_graph.py`、`test_approvals.py`（审批/越权/幂等/超时/503）、`test_approvals_pg.py`（含并发与授权隔离）、`test_playbooks.py`、`test_classify_eval.py`（50 条意图分类，规则路径 50/50，样本内）；审批通过后工单真正落库 |
| 模型网关 + 成本看板 + 回放（W4 D16–D20） | ✅ 已完成 | `gateway/` 规则路由 / OpenAI 兼容 + Ollama / failover；`model_calls` 与 `runs` 同事务计量；`tests/test_gateway.py`、`test_agent_llm.py`、`test_metrics_pg.py`；前端 `/runs`、`/runs/:id`、`/console/cost` |
| 管理后台（W5 D21–D24） | ✅ 已完成 | 知识库上传/切片/重建索引；工具启用/试调用；角色矩阵；审批中心；`tool_settings`（迁移 0007）与 `tools/policy.py`；`tests/test_admin_tools.py`、`test_tools_policy_pg.py` |
| 私有化交付（W6 D26–D28） | ✅ 已完成 | 50 条 RAG 评测 + 50 条意图分类评测与归因报告；api/web Dockerfile + compose `full` profile + 离线 compose；SSE 压测脚本；三条剧本 demo 脚本；D29 文档收尾中 |
| 孤儿 run 回收（W6 后加固） | ✅ 已完成 | 进程崩溃后停在 `running` 的 run，超过 `ONCALL_STALE_RUN_MIN`（默认 10 分钟）无事件即追加 `run.failed(RUN_INTERRUPTED)`；后台任务 + `make reap`；`tests/test_recovery.py`、`test_recovery_pg.py`（并发只写一条）；[ADR-0017](docs/decisions/0017-stale-run-recovery.md) |
| 引用跳全文（W5 D24 收尾） | ✅ 已完成 | 引用角标打开全文：`GET /kb/documents/{id}/preview` 登录即可（与检索同一可见性），`chunk_id` 优先/`ord` 兜底定位并高亮；`tests/test_rag_preview.py`、`test_kb_preview.py`（员工可读/404/401）；[ADR-0018](docs/decisions/0018-citation-fulltext-preview.md) |
| 文档级可见性（W6 后补） | ✅ 已完成 | `visibility=public / roles` + `allowed_roles`（迁移 0008）；召回 SQL 在 `LIMIT` 前过滤、预览同一规则、不可见 404；上传带范围、`PATCH .../access` 只改范围（`chunk_id` 不变）；`tests/test_rag_acl.py`、`test_rag_pg.py`（4×6 可见性矩阵）、`test_kb_api.py`、`test_kb_preview.py`；[ADR-0019](docs/decisions/0019-document-level-access.md) |
| 多轮上下文（W6 后补） | ✅ 已完成 | `RunStore.recent_turns` 按「用户 + `session_id`」取最近 3 轮（迁移 0009 索引），3 轮 / 1200 字预算；追问拼进 `context_query`，引用仍只来自本轮检索；「清空对话」换新 `session_id`；`tests/test_history.py`、`test_agent_runtime.py`、`test_store_contract.py`、`test_chat_stream.py`（同会话追问引用 VPN / 换会话拒答）；[ADR-0020](docs/decisions/0020-multi-turn-context.md) |
| 数据保留清理（W6 后补） | ✅ 已完成 | 终态 run 超过 `ONCALL_EVENT_RETENTION_DAYS`（默认 180 天）后按 run 整场删除事件并写 `events_pruned_at`（迁移 0010）；`model_calls` 按 `ONCALL_MODEL_CALL_RETENTION_DAYS` 删明细、`runs` 汇总保留；后台每 6 小时、单轮最多 10 批（事件与计量各 200 行/批）+ `make prune` / `prune --dry-run`；回放页标明事件已清理并从 `run.output` 兜底展示最终回答；`tests/test_retention.py`、`test_store_contract.py`（`_exercise_prune`）、`test_runs_api.py`、`test_metrics_pg.py`；[ADR-0021](docs/decisions/0021-data-retention.md) |
| 回答内容回收（W6 后补） | ✅ 已完成 | 回答引用快照落 `runs.cited_document_ids`（迁移 0011，含存量回填）；读详情/事件/幂等重放/多轮历史时按**当前**可见性校验，任一篇不可见就整场回收（fail-closed，`admin` 除外，恢复范围自动恢复）；`tests/test_runs_content.py`、`test_runs_api.py`、`test_chat_stream.py`、`test_rag_acl.py`、`test_rag_pg.py`、`test_store_contract.py`；[ADR-0022](docs/decisions/0022-run-content-visibility.md) |
| run 正文按时间保留（W6 后补） | ✅ 已完成 | 终态 run 超过 `ONCALL_RUN_CONTENT_RETENTION_DAYS`（默认 180 天）后清空 `runs.input/output` 并写 `content_pruned_at`（迁移 0012），只留状态/计量/失败归因/引用快照；强制正文保留期 ≥ 事件保留期（事件里是同一段正文）；详情返回空正文 + 标记、幂等重放 `410 CONTENT_EXPIRED`、多轮历史自然剔除；`tests/test_retention.py`、`test_store_contract.py`（`_exercise_prune_contents`）、`test_runs_api.py`、`test_chat_stream.py`、`test_runs_content.py`、`test_config.py`；[ADR-0023](docs/decisions/0023-run-content-retention.md) |
| 多轮评测（W6 后补） | ✅ 已完成 | `make eval-multiturn`：`app/eval/multiturn.py` + 17 条用例（12 指代 + 4 话题切换 + 1 诊断），只判最后一轮；指代轮要求引用命中标注文档且**空会话隔离对照**成立，切换轮要求命中新话题且不含上一轮话题、单独提问必须也能命中；门槛 `coref_acc` / `shift_acc` 各 ≥ 85%，诊断项不计入；评测顺带修好连续追问丢话题锚点（按时间累积最近 3 轮问题）与「那 + 新话题」被稀释（追问原句优先，ADR-0025）；`tests/test_multiturn_eval.py`、`test_history.py`、`test_rag_retrieve.py`；[ADR-0024](docs/decisions/0024-multiturn-eval.md)、[ADR-0025](docs/decisions/0025-followup-original-first.md) |
| 个人日预算（W6 后补） | ✅ 已完成 | `user_budgets` 表（迁移 0013）+ `GET/PUT/DELETE /admin/budgets`；网关在模型调用前先扣全局、再扣个人，个人不足时把全局预扣还回去再 `run.failed(BUDGET_EXCEEDED)`（不花钱、不占全局额度）；`ONCALL_USER_DAILY_BUDGET_CNY` 默认 0 = 不限，覆盖 2s 缓存、改完不重启；成本页新增「个人日预算」卡片；`tests/test_budgets.py`、`test_budgets_pg.py`；[ADR-0026](docs/decisions/0026-user-daily-budget.md) |
| 审批快照保留（W6 后补） | ✅ 已完成 | 已决议审批的 `state` 按 `ONCALL_RUN_CONTENT_RETENTION_DAYS`（默认 180 天）清空为 `{}`，挂起的不清；参数/理由/决议人保留，无迁移、幂等；`approval_grants` 过期即删；清理任务与 `prune --dry-run` 输出 `approval_snapshots` / `approval_grants`；`tests/test_retention.py`、`test_approvals_pg.py`；[ADR-0027](docs/decisions/0027-approval-snapshot-retention.md) |
| 预算可观测性（W6 后补） | ✅ 已完成 | 全局与个人账本加只读快照；预扣时间戳写进同一个 reservations hash（旧副本无 ts → 年龄未知、不报 stale），用户用当日集合枚举；`GET /admin/budgets/usage` 返回已用、未结算笔数/金额与 300 秒判据下的卡住笔数，账本故障 503 不降级；成本页合并配置与账本（未知花费显示「—」）；`tests/test_budget_usage.py`；[ADR-0028](docs/decisions/0028-budget-observability.md) |
| 工单自助查询与详情（W6 后补） | ✅ 已完成 | `query_tickets` 注册为只读工具（2000ms、身份注入、只查 `requester=当前用户`，创建时间倒序取最近 N 条）；「我的工单/工单进度/修好了吗」等状态问法保持 `knowledge`（不再被「报修」误判成写操作），规则计划选中该工具，`finalize` 以工单表作答、不拼知识库引用；按 [ADR-0038](docs/decisions/0038-ticket-detail.md) 支持可选 `ticket_id`：按 `requester` 过滤的单条详情（描述/处理人/解决时间），查不到返回 null、不泄露存在性；`tests/test_tickets.py`、`test_tools_guard.py`、`test_agent_graph.py`；[ADR-0029](docs/decisions/0029-ticket-self-service-query.md) |
| 会话列表与历史会话继续（W6 后补） | ✅ 已完成 | 不建表，按 `runs.session_id` 投影（复用 `idx_runs_user_session_time`，无迁移）；`GET /sessions` 只读本人、标题取最早非空 `input`；左侧会话栏点开最近 20 条 run，拼只读 transcript（正文过期/引用回收/未结束/失败各有占位），继续对话沿用同一 `session_id`；`tests/test_sessions_api.py`、`test_store_contract.py`（`_exercise_sessions`）、`web/src/features/chat/history.test.ts`；[ADR-0030](docs/decisions/0030-session-list.md) |
| 会话列表与历史轮次分页（W6 后补） | ✅ 已完成 | `/sessions` 用 `(updated_at, session_id)` keyset 游标（base64url JSON，非法 400 `INVALID_CURSOR`）；会话内用 `/runs` 已有游标翻更早轮次（`prependHistory`）；翻页期间新 run 可能造成重复/跳过，刷新即重置；无新表/索引/迁移；[ADR-0033](docs/decisions/0033-session-history-pagination.md) |
| 历史引用回放（W6 后补） | ✅ 已完成 | `runs.citations`（迁移 0014）存 `message.completed` 的完整引用快照，历史会话还原角标并复用现有全文预览；只保留已知字段、最多 50 条，正文按 ADR-0023 清空时一起置空，`content_redacted` / 过期时详情返回 `[]`；迁移前旧 run 不回填；`test_store_contract.py`、`test_runs_api.py`；[ADR-0031](docs/decisions/0031-run-citations-replay.md) |
| PDF 解析子进程隔离（W6 后补） | ✅ 已完成 | `.pdf` 在 `spawn` 子进程里解析（PyMuPDF/pypdf 逻辑不变），60 秒超时先 terminate 再 kill；崩溃/超时/管道异常都收敛成 `ParseError` → 上传接口 422，不再带走 API；本机实测 1 页文本 PDF 预热后 5 次中位数约 0.30 秒启动开销（Linux/大文件未测），未做内存 rlimit/常驻池；`test_rag_pdf_isolation.py`；[ADR-0032](docs/decisions/0032-pdf-parse-subprocess.md) |
| 资产查询接表（W6 后补） | ✅ 已完成 | `query_cmdb` 改读 `assets` 表（内存/PG 双实现），`owner_id` 从 schema 删除、由 `ToolGuard` 注入，模型传身份字段会被 `validate_args` 拒绝；返回 `{"assets": [...], "count": N}`，空列表是合法结果，`finalize` 支持单台/多台/空/失败；换真实 CMDB 只替换 repository；无迁移；`tests/test_assets.py`、`test_assets_pg.py`；[ADR-0034](docs/decisions/0034-cmdb-assets-table.md) |
| 历史运行过程回放（W6 后补） | ✅ 已完成 | `GET /runs/{id}` 从 `tool.call/result`、`approval.required/resolved` 投影只读 `timeline`，按 `call_id` / `approval_id` 合并，步骤与 `message.delta` 不进入；最多 20 项、超出 `timeline_truncated=true`；跟随回答可见性，正文回收/过期/事件清理时 `timeline_available=false`；不返回审批人 `resolved_by`/`scope`；历史回答下方折叠展示，只读；无新表/迁移；`tests/test_run_timeline.py`、`test_runs_api.py`；[ADR-0035](docs/decisions/0035-run-timeline-replay.md) |
| 批量会话详情（W6 后补） | ✅ 已完成 | 新增 `GET /sessions/{id}/runs`：一页 run 的正文/引用/运行过程一次返回，打开会话与加载更早各只发 1 次请求（原来 21 次前端请求，且每条详情服务端还要另查事件与可见性）；整页引用合并成一次可见性查询，事件按 run 批量取（Postgres 窗口函数）；不含 `model_calls`，无新表/迁移；无游标且查不到会话返回 404，游标越界返回 200 空页；`tests/test_sessions_api.py`、`test_store_contract.py`（`_exercise_events_for_runs`）；[ADR-0036](docs/decisions/0036-session-detail-batch.md) |
| 工具配置变更历史（W6 后补） | ✅ 已完成 | 新增追加式 `tool_setting_changes`（迁移 0015）：每个真正变化的工具一行，`before`/`after` 存完整覆盖快照，与 `tool_settings` 写入同事务；`GET /admin/tools/{name}/history?limit=`（admin-only、倒序、最多 100）；ToolsPage 每行「历史」Dialog 展示时间/操作人/来源/`before → after`；历史长期保留、不提供回滚；`tests/test_tool_history.py`、`test_tool_history_pg.py`；[ADR-0037](docs/decisions/0037-tool-setting-history.md) |

### 评测与压测

```bash
make eval        # 50 条：事实 15 / 排查 15 / 多跳 10 / 负样本 5 / 注入 5
make eval-classify  # 50 条意图分类（knowledge 18 / asset 16 / ticket 16）
make eval-multiturn  # 17 条多轮（12 指代 + 4 话题切换 + 1 诊断；隔离对照双向，ADR-0024/0025）
make loadtest    # 100 请求 / 20 并发 / 20 用户，打完整 SSE run
make demo        # 三条剧本（第二条含审批）打到本机 API
```

W6 基线（3 轮均值，mock 规则路径，口径见 [baseline-v1](docs/eval/baseline-v1.md)）：
`recall@5 100%`、`cite_acc 97.09%`、`answer_acc 100%`、`refusal_correct 100%`、
`injection_blocked 100%`、`tool_success_rate 100%`、`avg_steps 7`、`p95 81ms`。
**这是样本内结果**：50 条全部参与过调参，不能当泛化效果或模型效果。

意图分类（D11，[classify-v1](docs/eval/classify-v1.md)）：50 条人工标注，
规则路径 `intent` / `incident` 联合 **50/50**；同样属样本内，且只覆盖规则路径，
模型兜底路径需要真实 provider 才能量化。

多轮（[multiturn-v2](docs/eval/multiturn-v2.md)）：16 条用例分两个方向——指代轮要求
「引用命中标注文档 **且** 同一句单独提问时不命中」（`coref_acc`），话题切换轮要求
「命中新话题 **且** 不含上一轮话题，同一句单独提问时必须能命中」（`shift_acc`）。
规则路径 `coref_acc` **12/12**、隔离对照 12/12、`shift_acc` **4/4**、切换前提 4/4；
诊断项「没点名文档的新话题」0/1（仍被上一轮稀释，已知边界，不计入门槛）。
同样属样本内，且只覆盖被追问启发式识别的句子。

压测（2026-11-09，Windows 11 + WSL2 **16 vCPU / 15GiB**，Docker 29.1.3，
单 API 容器 + Postgres/Redis 容器，mock 模式，100 请求 / 20 并发 / 20 用户）：

| 指标 | 结果 |
|---|---|
| 成功率 | 100/100 |
| 吞吐 | 12.60 run/s |
| 事件吞吐 | 306.6 条/s |
| p95 端到端 | 1814ms |
| p95 首事件 | 238ms |
| 平均事件数 | 24.3 |

> 这是开发机链路验证，**不是 8C16G 生产容量验收**；换机器/换真实模型必须重跑，
> 并把 CPU、内存、Postgres 版本、mock/real 一起写进口径。

> 首次拉仓库执行 `uv sync --all-extras`（后端）与 `pnpm install`（前端）；
> `--all-extras` 同时装 rag（pypdf / python-docx）与 dev 依赖，漏装 rag 时解析相关用例会 skip。

## 已知局限

- 评测集 50 条，但**全部参与过调参**（负样本 5、注入 5），100% 是样本内结果；
  真实泛化需要另建不参与调参的盲测集，当前没有
- 压测脚本已在开发机跑通；**8C16G 生产容量尚未验收**，README 不写未测出的 QPS/并发承诺
- `web/Dockerfile` 的 Node 构建层在本机因 registry 拉取超时未跑完；运行态用本地 `pnpm build`
  + Nginx 镜像验证（SPA、SSE、审批链路均通），正式交付前需在同网络环境重跑 `make stack`
- 默认 embedding 是确定性哈希，不是语义模型；生产建议切 `ONCALL_EMBEDDING_PROVIDER=http` 接 bge-m3
- PDF 用 `pypdf` 提取文本层，解析在独立子进程（60 秒超时，崩溃/超时返回 422，[ADR-0032](docs/decisions/0032-pdf-parse-subprocess.md)）；扫描件不做 OCR；复杂版面/表格请先转 DOCX/MD
- 重排是确定性规则，bge-reranker 仍待有模型服务后再评估
- 中文检索用「单字 + 二元组」，长句与跨文档对比仍弱于 zhparser + 领域词典
- 默认 `ONCALL_MOCK_MODE=true`：走确定性规则，没有真实模型调用，成本恒为 0；
  真实模型的分类/计划质量与成本需要配置 provider 后另跑一轮（当前未测）
- 答案仍是指令抽取 + 模板，不是生成；W4 的模型只用于 classify 兜底与 plan
- 8 节点图用手写转移表而不是 LangGraph（[ADR-0012](docs/decisions/0012-explicit-agent-scheduler.md)），W4 评估后仍未启用
- `query_cmdb` 读本地 `assets` 表（只查本人，seed 的 200 台可见），换真实 CMDB 只替换
  `app/tools/assets.py` 的 repository；`owner_id` 索引、资产分页/搜索与共享设备权限未做
- 审批决议、`approval.resolved` 与拒绝/超时的 `run.failed` 已同事务（[ADR-0016](docs/decisions/0016-approval-decision-transaction.md)）；
  但通过后的恢复执行仍在事务外，进程在工具执行后、事件落库前崩溃仍可能停在非终态。
  超过 `ONCALL_STALE_RUN_MIN`（默认 10 分钟）无事件的 `running` run 会被回收为
  `RUN_INTERRUPTED`（[ADR-0017](docs/decisions/0017-stale-run-recovery.md)），只收敛状态、
  不自动重试写工具；工单是否已创建仍需人工按 run_id 对账
- 工具 schema 在管理页只读；配置覆盖只到「启用/角色」，且多副本部署最长 2s 生效（[ADR-0014](docs/decisions/0014-tool-policy-overrides.md)）
- 工具配置变更历史只记管理 API：`changed_by` 是 JWT `sub`（没有姓名/部门目录），权限矩阵一次保存没有 batch id、只能按工具逐条看；没有保留期/冷归档、导出、时间范围筛选与回滚按钮，直接改数据库也不会留下应用层记录；并发管理写入是 last-write-wins，`before` 不保证接上前一条 `after`；工具下线后只能通过 API 按旧名字查历史，管理页不再有入口（[ADR-0037](docs/decisions/0037-tool-setting-history.md)）
- 引用全文预览是按切片重组的正文，不是原始文件渲染（PDF 排版/表格样式会丢）；没有列表接口、只能凭已知
  `document_id` 打开（[ADR-0018](docs/decisions/0018-citation-fulltext-preview.md)）
- 多轮上下文只有 3 轮 / 1200 字，追问判定是关键词启发式；连续追问的检索词按链累积（最多 80 字），
  点名了语料文档**且检索明显领先**的新话题会切回原句（`topic_head` + 分差 ≥ 0.10，
  [ADR-0025](docs/decisions/0025-followup-original-first.md)）；**没点名任何文档**的新话题（多轮评测
  诊断项 0/1），以及点名了但分差不够的（如「那差旅怎么申请」0.547 vs 0.530，退化为拼上文）仍会被
  上一轮稀释，见 [multiturn-v2](docs/eval/multiturn-v2.md)；点不出具体文档的追问多一次检索，
  真实嵌入服务下的延迟未做基准；
  刷新页面即新会话，没有跨会话记忆；上一轮引用的文档被收权后该轮会剔出历史
  （[ADR-0022](docs/decisions/0022-run-content-visibility.md)），但历史仍来自当时展示过的
  `runs.output`；回答进历史时截断到 400 字；多轮评测只覆盖被启发式识别的追问、判定是文档级，
  样本内（[ADR-0024](docs/decisions/0024-multiturn-eval.md)）。
- 文档级可见性只有 `public` / `roles` 两档：没有按用户授权、部门继承、临时授权与密级；
  `admin` 是知识库所有者、可读全部正文（合规要求「管理员也不能看内容」时需要在部署层拆角色）；
  角色名不做白名单，拼错会让文档除管理员外谁都看不到（控制台可见并可改）。召回多一次
  `kb_documents` join，v1 规模下既没验证执行计划、也没做延迟对比基准
  （[ADR-0019](docs/decisions/0019-document-level-access.md)）
- 保留清理只删事件、正文、计量明细、审批快照与过期会话授权：超过 180 天的 run 只能看摘要，不能回放；
  已决议审批的 `state` 也被清空，参数/理由/决议人保留但不能再从快照恢复执行；没有冷归档，
  现场要留更久只能调大保留天数；`model_calls` 删除后，超出窗口的
  区间成本明细不可再核对（`runs` 汇总仍在）；清理任务没有性能基准（单批 200 场、每轮
  10 批、6 小时间隔是保守默认值，按 1–2 条计量/run 约 4000–8000 run/天）
  （[ADR-0021](docs/decisions/0021-data-retention.md)、[ADR-0023](docs/decisions/0023-run-content-retention.md)、
  [ADR-0027](docs/decisions/0027-approval-snapshot-retention.md)）
- 回答内容按权限回收：引用文档被改窄/删除后，详情、事件、幂等重放与多轮历史都不再展示
  旧回答（[ADR-0022](docs/decisions/0022-run-content-visibility.md)）。代价是 fail-closed——
  重新上传会换 `document_id`，旧引用因此按不可见处理；回收只覆盖知识库引用
- 问答正文按时间清理：超过 `ONCALL_RUN_CONTENT_RETENTION_DAYS`（默认 180 天）后
  `runs.input/output` 被**不可逆**清空，详情只剩摘要，那一轮也从多轮历史消失
  （[ADR-0023](docs/decisions/0023-run-content-retention.md)）。正文保留期不允许短于事件保留期
  ——事件里是同一段回答正文，想更早删正文要连事件一起调；按用户/租户的差异化保留期没有做
- 成本控制有单 run / 当日全局 / **按用户**三层，但没有租户或部门维度（`Identity` 只有
  `user_id` + `roles`）；个人额度按 UTC 日累计、**不从当天已花的历史回填**，被拦下是
  `run.failed(BUDGET_EXCEEDED)` 而不是 429；mock 模式不经过网关，个人预算不生效
  （[ADR-0026](docs/decisions/0026-user-daily-budget.md)）。全局与个人是两笔独立预扣，
  进程崩在两次之间会留下全局预留（日切自愈，偏保守）。预扣泄漏能在成本页看到，但报表只是
  当前 UTC 日采样，不自动对账、没有历史趋势；旧格式预扣（升级前写入、无时间戳）年龄未知，
  `oldest_age_s` 为 null、不计 stale（[ADR-0028](docs/decisions/0028-budget-observability.md)）
- 工单自助查询只覆盖本人：可按单号看单条详情（描述截 200 字、处理人、解决时间），但描述与
  处理人只展示 `tickets` 表里已有的值——`create_ticket` 暂不收集描述，自建工单的详情没有
  「问题」行；列表仍只有最近 N 张摘要，没有分页、时间范围与按资产筛选；IT 管理员不能查他人
  （需要新的权限模型）；状态中文映射写死在 `finalize`；关键词规则也可能把流程咨询（如
  「报修进度怎么查」）误当成查工单、而不是走知识库；`requester` 列暂未加索引（单用户工单量小）
  （[ADR-0029](docs/decisions/0029-ticket-self-service-query.md)、
  [ADR-0038](docs/decisions/0038-ticket-detail.md)）
- 会话列表首屏是最近 20 个会话、每个会话 20 轮，底部/顶部可继续翻页，但没有会话搜索、
  重命名、删除与虚拟滚动；翻页期间有新 run 时可能重复或跳过一页，刷新即重置
  （[ADR-0033](docs/decisions/0033-session-history-pagination.md)）；历史回答的工具/审批以
  「运行过程」折叠区回放（[ADR-0035](docs/decisions/0035-run-timeline-replay.md)），但最多
  20 项、单条工具结果没有字节上限，不显示审批人；正文被回收/过期或事件已清理后不可回看。
  会话历史改为一页一次请求（[ADR-0036](docs/decisions/0036-session-detail-batch.md)），
  但仍是游标翻页、不能跳到某一轮，批量响应也没有单条 run 字节上限。
  历史回答的引用角标已按
  `runs.citations` 还原（[ADR-0031](docs/decisions/0031-run-citations-replay.md)），
  但迁移前的旧 run 没有快照；窄屏（<640px）隐藏
  会话栏，暂没有抽屉入口；刷新不自动恢复最后一次会话（需在左侧点开）；正文按
  ADR-0023 清空后标题为 null，显示「无标题」但会话仍保留
  （[ADR-0030](docs/decisions/0030-session-list.md)）
- 引用快照随正文一起保留 180 天，过期后历史角标消失、只留 `cited_document_ids`
  供权限回收；仍不支持单条引用级权限（一篇不可见就整场回收，ADR-0022），迁移前的
  run 也不能补出角标
  （[ADR-0031](docs/decisions/0031-run-citations-replay.md)）
- iframe + postMessage 嵌入形态（W5 D25）暂缓，需要来源白名单与 CSP 部署决策

## License

MIT
