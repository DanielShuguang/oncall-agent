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
| 回答错了怎么查？ | 看日志 | 每个答案带原文引用；每次运行可完整回放 |
| 花了多少钱？ | 月底看账单 | 单次对话实时计量，按 run / 天 / 模型聚合 |
| 能不能私有化？ | 依赖云 API | 本地模型（vLLM / Ollama）+ docker-compose 一键部署，8C16G 可跑 |

## 核心能力

1. **RAG 知识库**：混合检索（BM25 + 向量 + RRF）+ rerank + 引用溯源 + 无命中兜底
2. **工具层**：MCP Server 封装内部系统（CMDB / 工单 / 知识检索 / 只读诊断 / 开单）
3. **Agent 运行时**：显式 8 节点状态机（LangGraph 可选），只有 2 个节点调 LLM（规则优先）
4. **工具治理**：白名单、会话级权限、单工具超时、错误分类重试、业务降级、保留字段拒绝
5. **人工审批**：写操作必须确认，支持"本会话内允许"
6. **模型网关**：多模型接入、规则路由、限流、每日预算、成本埋点
7. **可观测**：事件落库、断线续跑、按 run 回放、成本与质量看板
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
│ 状态机  │   │ 路由/降级/成本│  │ MCP + 治理     │
└───┬────┘   └─────┬──────┘  └────┬─────────┘
    │              │              │
┌───▼──────────────▼──────────────▼───────────┐
│ Postgres(+pgvector) / Redis / 事件表          │
│ CMDB · 工单系统 · 知识库（可对接或模拟）        │
└──────────────────────────────────────────────┘
```

详细设计见 [docs/01-architecture.md](docs/01-architecture.md)。

## 快速开始

### 0. 前置

- Docker Desktop（含 Compose）
- Python 3.12 + [uv](https://docs.astral.sh/uv/)
- Node.js 20+ + pnpm

### 1. 起中间件

```bash
cp .env.example .env
docker compose up -d          # postgres:16 + pgvector, redis:7
```

### 2. 起后端

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

### 3. 签发本地 token

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

### 4. 起前端

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
| [06-tool-governance](docs/06-tool-governance.md) | MCP、白名单、权限、超时、审批 |
| [07-frontend-design](docs/07-frontend-design.md) | 路由、状态机、组件、交互 |
| [08-eval-metrics](docs/08-eval-metrics.md) | 评测集与指标口径 |
| [09-deploy-private](docs/09-deploy-private.md) | 私有化、离线镜像、信创 |
| [10-roadmap-6weeks](docs/10-roadmap-6weeks.md) | 30 天逐日计划与验收 |
| [11-dev-setup](docs/11-dev-setup.md) | 环境搭建与排错 |

> 用 AI 编码助手改这个仓库时，先让它读 [AGENTS.md](AGENTS.md)——那是约束清单（硬规则、recipe、反模式），不是背景介绍。

## 状态

| 模块 | 状态 | 验证方式 |
|---|---|---|
| 文档（12 篇 + 13 篇 ADR + 评测基线） | ✅ 完成 | — |
| 前端骨架（状态机 / SSE 客户端 / 页面 / 审批卡 / 运行回放 / 成本页） | ✅ 可用 | `tsc --noEmit`、`oxlint 0`、`oxfmt --check` 通过；`vitest` 28/28；`pnpm build` 成功 |
| 后端骨架（事件契约 / SSE / 健康检查） | ✅ 可运行 | 默认 `pytest` **180 passed + 12 skipped**；设 `ONCALL_TEST_DATABASE_URL` 后 **192 passed**（含 Postgres 契约、并发 seq、pgvector 检索、审批并发、计量一致性） |
| 本地 JWT（W1 D2） | ✅ 已完成 | `tests/test_auth.py` 20 条：签发/验签、过期、alg=none、401 JSON、OpenAPI Bearer、run 归属隔离 |
| 事件落库 + 断线续传（D4） | ✅ 已完成 | `alembic upgrade head` + `alembic check` 无漂移；`tests/test_store_contract.py`（内存 + Postgres 契约）、`tests/test_chat_stream.py`（落库、幂等回放、503 语义） |
| 最小 Agent 运行时（W1 D5） | ✅ 已完成 | `tests/test_agent_runtime.py` 9 条：工具真实执行、检索引用、写操作挂起审批、工具失败降级、步数/时长上限 |
| RAG 全链路（W2 D6–D10） | ✅ 已完成 | 50 篇 seed 知识库（含过期版本/冲突/噪声）；解析→切分→pgvector+tsvector→RRF→阈值→引用；`tests/test_rag_parse.py`、`test_rag_retrieve.py`、`test_rag_pg.py`、`test_kb_api.py`；评测基线 [docs/eval/baseline-v0](docs/eval/baseline-v0.md)（20 条，recall@5 100%、cite_acc 91.7%） |
| 工具治理五道闸门 + 超时重试 | ✅ 已实现 | `tests/test_tools_guard.py` 20 条：权限/保留字段/入参白名单/enum/超时重试/身份注入/伪造身份 |
| 8 节点图 + 审批闭环（W3 D11–D15） | ✅ 已完成 | `tests/test_agent_graph.py`、`test_approvals.py`（审批/越权/幂等/超时/503）、`test_approvals_pg.py`（含并发与授权隔离）、`test_playbooks.py`；审批通过后工单真正落库 |
| 模型网关 + 成本看板 + 回放（W4 D16–D20） | ✅ 已完成 | `gateway/` 规则路由 / OpenAI 兼容 + Ollama / failover；`model_calls` 与 `runs` 同事务计量；`tests/test_gateway.py`、`test_agent_llm.py`、`test_metrics_pg.py`；前端 `/runs`、`/runs/:id`、`/console/cost` |

> 首次拉仓库执行 `uv sync --all-extras`（后端）与 `pnpm install`（前端）；
> `--all-extras` 同时装 rag（pypdf / python-docx）与 dev 依赖，漏装 rag 时解析相关用例会 skip。

## 已知局限

- 评测集 v0 只有 20 条（负样本 2、注入 2），阈值与重排权重也在同一批用例上调过，结论只能说方向性
- 默认 embedding 是确定性哈希，不是语义模型；生产建议切 `ONCALL_EMBEDDING_PROVIDER=http` 接 bge-m3
- PDF 用 `pypdf` 提取文本层，扫描件不做 OCR；复杂版面/表格请先转 DOCX/MD
- 重排是确定性规则，bge-reranker 仍待有模型服务后再评估
- 中文检索用「单字 + 二元组」，长句与跨文档对比仍弱于 zhparser + 领域词典
- 默认 `ONCALL_MOCK_MODE=true`：走确定性规则，没有真实模型调用，成本恒为 0；
  真实模型的分类/计划质量与成本需要配置 provider 后另跑一轮（当前未测）
- 答案仍是指令抽取 + 模板，不是生成；W4 的模型只用于 classify 兜底与 plan
- 8 节点图用手写转移表而不是 LangGraph（[ADR-0012](docs/decisions/0012-explicit-agent-scheduler.md)），W4 评估后仍未启用
- `query_cmdb` 仍是内置假数据，接真实 CMDB 留到后续
- 审批决议与 run 事件写入不在同一事务：进程在 approve 后崩溃可能留下 `running`，
  当前不自动重试写工具（避免重复开单），需按 run_id 对账（docs/06 §7）

## License

MIT
