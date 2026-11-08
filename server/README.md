# server · FastAPI + LangGraph

## 目录

```
app/
├─ main.py            FastAPI 应用工厂
├─ api/               路由（薄层：校验、鉴权、调 service）
├─ core/              配置、SSE 编码、内存存储（W1 D4 换 PG）、限流、预算
├─ schemas/           Pydantic 模型（事件契约在此定义）
├─ models/            SQLAlchemy 模型
├─ agent/             状态机、节点、运行时、demo 事件流
├─ tools/             MCP 工具 + 治理（ToolSpec / ToolGuard）
├─ gateway/           模型网关（多 provider、路由、计量）
├─ rag/               解析、切分、索引、检索、引用
└─ eval/              评测集与执行器
```

## 启动

```bash
uv sync --all-extras
uv run uvicorn app.main:app --reload --port 8000
```

只要最小依赖（够跑 W1）：

```bash
uv sync
```

## 当前实现状态

| 模块 | 状态 |
|---|---|
| `main.py` / `api/health.py` | ✅ 可用（探 db + redis） |
| `api/chat.py` | ✅ 返回**假事件流**（W1 D3 骨架） |
| `api/runs.py` | ✅ 内存存储 + `after_seq` 补拉（W1 D4 换 PG） |
| `tools/registry.py` | ✅ 五道闸门、超时、重试、审批标记已实现 |
| `agent/*` | 🚧 `state.py` 已定义；`graph.py` 为占位 |
| `rag/*` `gateway/*` `eval/*` | 🚧 待实现 |

## 约定

- `api/` 不放业务逻辑，不写 SQL
- 事件类型只在 `schemas/event.py` 定义，前端从 OpenAPI 生成
- 工具治理只在 `tools/registry.py` 实现，**不要在 MCP server 里重复校验**
- 所有时间戳 UTC
