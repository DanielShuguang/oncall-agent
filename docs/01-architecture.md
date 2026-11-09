# 01 · 系统架构

## 1. 定位

OnCall 是一个**可私有化部署的企业服务台 Agent**。它不是聊天机器人，区别在于：

| 维度 | 聊天机器人 | OnCall |
|---|---|---|
| 输出 | 一段文本 | 文本 + 工具调用 + 工单 + 审批 |
| 失败 | 道歉 | 降级到人工，并留下可回放的现场 |
| 权限 | 无 | 会话级权限，工具执行前判定 |
| 写操作 | 无 | 有，但必须人工审批 |
| 成本 | 不可见 | 每次 run 实时计量 |

## 2. 分层与模块职责

```
┌──────────────────────────────────────────────────────────┐
│ web/  React 19 + Vite + Tailwind CSS                      │
│  features/chat    对话、事件时间线、审批卡、断线续传          │
│  features/console 知识库、工具注册、权限矩阵、成本看板        │
└───────────────┬──────────────────────────────────────────┘
                │ HTTP + SSE
┌───────────────▼──────────────────────────────────────────┐
│ server/app/api    FastAPI 路由（薄层，不放业务）             │
│ server/app/core   配置、鉴权、限流、预算、SSE 编码、存储      │
└───────────────┬──────────────────────────────────────────┘
                │
     ┌──────────┼───────────┬──────────────┐
     ▼          ▼           ▼              ▼
┌─────────┐ ┌────────┐ ┌──────────┐ ┌──────────┐
│ agent/  │ │gateway/│ │ tools/   │ │  rag/    │
│ 状态机  │ │模型网关 │ │ MCP+治理 │ │ 检索     │
└─────────┘ └────────┘ └──────────┘ └──────────┘
                │
┌───────────────▼──────────────────────────────────────────┐
│ PostgreSQL（业务 + 向量 + 事件）  Redis（限流 + 预算）      │
│ 外部系统：CMDB / 工单 / 知识库（可 mock 或对接）             │
└──────────────────────────────────────────────────────────┘
```

### 模块职责边界（重要：跨层调用是设计事故）

| 模块 | 只做 | 不做 |
|---|---|---|
| `api/` | 参数校验、鉴权、调用 service、返回/流式 | 业务规则、SQL、提示词 |
| `core/` | 配置、日志、SSE 编码、存储抽象、限流、预算 | 业务语义 |
| `agent/` | 状态机编排、节点逻辑、提示词 | 直接调 HTTP、直接写库 |
| `gateway/` | 模型选择、调用、计量、降级 | 业务判断 |
| `tools/` | 工具注册、参数校验、权限、执行、超时 | 提示词、模型选择 |
| `rag/` | 解析、切分、索引、检索、引用 | 生成 |

## 3. 三条核心时序

### 3.1 普通问答（只读）

```
用户 ──POST /api/chat/stream──► api.chat
                                   │ 建 run，落库
                                   ▼
                              agent.run()  ──► gateway.chat()
                                   │              │ 记录 model_call
                                   │◄─────────────┘
                                   ├─ event: step.started(classify)
                                   ├─ event: step.completed
                                   ├─ event: step.started(retrieve)
                                   ├─ event: tool.call(search_kb)  ← 只读工具，自动执行
                                   ├─ event: tool.result
                                   ├─ event: message.delta × N
                                   ├─ event: message.completed
                                   └─ event: run.completed
                                   │
用户 ◄────SSE（id=seq）────────────┘

每条事件：先写 run_events，再推给前端（先落库后推送，保证可回放）
```

### 3.2 写操作 + 人工审批

```
agent 决定 create_ticket
   │
   ├─ tools.guard: 白名单 ✓ 角色 ✓ 保留字段 ✓
   ├─ tool.write == true  → 不执行，挂起
   ├─ event: approval.required {approval_id, tool, args, risk}
   │
用户点「批准」─POST /api/approvals/{id}/resolve
   │
   ├─ 校验：审批人 ≠ 申请人；角色 ∈ ONCALL_APPROVER_ROLES；run 已进入待审批
   ├─ 原子迁移 pending → approved（并发重复决议只执行一次）
   ├─ event: approval.resolved
   ├─ 从 approvals.state 快照恢复 act（allow_write=true，带超时）
   ├─ event: tool.result
   └─ verify → finalize → run.completed
```

**关键设计**：审批不是"再问一次模型"，而是把执行权交还给人。模型永远不能自己批准自己；
拒绝/超时追加 `run.failed(APPROVAL_REJECTED|APPROVAL_TIMEOUT)`，写工具一次都不执行。

### 3.3 断线续跑

```
连接断开 → 前端记住 lastEventId
重连     → GET /api/runs/{id}/events?after_seq=N（补历史）
         → 若 run 仍在执行，再挂 SSE /api/runs/{id}/stream（增量）
事件表就是唯一真相源，前端状态可由事件重放得出
```

## 4. 状态与一致性

| 关注点 | 方案 |
|---|---|
| 事件顺序 | 每个 run 内 `seq` 由 DB 序列保证单调递增 |
| 幂等 | 客户端传 `client_msg_id`，重复提交返回同一 run |
| 并发 | 一个 run 同时只允许一个执行者（DB 行锁 / Redis 锁） |
| 超时 | 工具级超时 + run 级最大步数 + run 级总时长上限 |
| 崩溃恢复 | 超过 stale 阈值的 `running` run 由后台回收为 `failed(RUN_INTERRUPTED)`；只收敛状态，不重放写操作（[ADR-0017](decisions/0017-stale-run-recovery.md)） |
| 预算 | 每次模型调用前 `INCRBY` 预扣，超预算直接拒绝 |
| 限流 | 按用户滑动窗口（ZSET），超限在建 run 前返回 429 |

> W4 实现：`gateway/` 已接入 classify 兜底与 plan；`core/limits.py` 用 Redis
> 做滑动窗口限流与 UTC 日预算，Redis 不可用时退化为进程内实现并打 warning。
> mock 模式（`ONCALL_MOCK_MODE=true`）不经过网关，节点走确定性规则，成本恒为 0。

## 5. 技术栈（摘要）

| 层 | 选型 |
|---|---|
| 前端 | React 19 + TS + Vite + Zustand + Tailwind CSS 4 + ECharts |
| 流式 | SSE（`fetch` + `ReadableStream`，非 EventSource） |
| 后端 | Python 3.12 + FastAPI + Pydantic v2 + SQLAlchemy 2 + Alembic |
| 编排 | 显式 8 节点状态机（ADR-0012；LangGraph 可选，W4 评估后仍未启用） |
| 检索 | PostgreSQL 16 + pgvector + tsvector + RRF + 确定性重排（bge-reranker W4 可选） |
| 工具 | MCP（FastMCP），stdio + streamable HTTP |
| 模型 | OpenAI 兼容协议；Ollama（dev）/ vLLM（演示） |
| 观测 | 自研事件表 + 成本表 + 看板；Langfuse 可选 |
| 部署 | Docker Compose + 离线镜像 |

选型理由见 [decisions/](decisions/)。

## 6. 明确不做（非目标）

- ❌ 多 Agent 协作编排（v2）
- ❌ 模型微调/训练
- ❌ 完整 IM 客户端（只做 Web + 嵌入）
- ❌ 多租户 SaaS 与计费
- ❌ Computer Use / 浏览器自动化
- ❌ 自研代码补全模型

> 面试价值：能清楚说出"不做什么、为什么"，比列一堆功能更能证明判断力。

## 7. 部署形态

| 形态 | 场景 | 组成 |
|---|---|---|
| 开发 | 本机 | docker( pg+redis ) + uvicorn + vite |
| 演示 | 单机 docker compose | api + web + pg + redis，模型走 Ollama |
| 私有化 | 客户内网 | 离线镜像 + 外接客户 CMDB/工单 + 本地 vLLM |

资源基线：**8C16G 单机**（不含本地大模型）；含 7B 量化模型建议 16C32G。
