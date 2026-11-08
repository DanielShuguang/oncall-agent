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
3. **Agent 运行时**：LangGraph 状态机，8 个节点只有 2 个调 LLM（规则优先）
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
│LangGraph│   │ 模型网关     │  │ 工具运行时     │
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
uv sync
uv run uvicorn app.main:app --reload --port 8000
# 打开 http://127.0.0.1:8000/docs
```

### 3. 起前端

```bash
cd web
pnpm install
pnpm dev
# 打开 http://127.0.0.1:5173
```

前端已配置 `/api` 代理到 `http://127.0.0.1:8000`。

> 当前后端 `/api/chat/stream` 返回的是**假事件流**，用于先把"流式 + 状态机 + 续传"骨架跑通（对应路线图 W1 D3）。接真实 Agent 在 W1 D5 之后。

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
| 文档（12 篇 + 9 篇 ADR） | ✅ 完成 | — |
| 前端骨架（状态机 / SSE 客户端 / 页面） | ✅ 可用 | `tsc --noEmit`、`oxlint`、`oxfmt --check` 通过；`vitest` 18/18 通过；`pnpm build` 成功 |
| 后端骨架（事件契约 / SSE / 健康检查） | ✅ 可运行 | 默认 `pytest` 35 passed + 1 skipped；设 `ONCALL_TEST_DATABASE_URL` 后 36 passed（含 Postgres 契约与并发 seq） |
| 事件落库 + 断线续传（D4） | ✅ 已完成 | `alembic upgrade head` + `alembic check` 无漂移；chat 落库 23 帧后重启服务仍可补拉；同一用户同一 `client_msg_id` 重放不新增事件 |
| 工具治理五道闸门 + 超时重试 | ✅ 已实现 | `tests/test_tools_guard.py` 随 `make test` 通过 |
| RAG / LangGraph / 模型网关 / 评测 | 🚧 待实现 | 见 [路线图](docs/10-roadmap-6weeks.md) |

> 首次拉仓库先执行 `uv sync --all-extras`（后端）与 `pnpm install`（前端）。后端依赖在本次初始化机器上未安装完成，故运行时行为以你本地实际为准。

## License

MIT
