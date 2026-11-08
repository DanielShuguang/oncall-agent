# server · FastAPI + LangGraph

## 目录

```
app/
├─ main.py            FastAPI 应用工厂
├─ cli.py             本地签发 JWT（`python -m app.cli token`）
├─ api/               路由（薄层：校验、鉴权、调 service）
├─ core/              配置、数据库引擎、JWT 校验、SSE 编码、运行态存储
├─ schemas/           Pydantic 模型（事件契约/知识库响应）
├─ models/            SQLAlchemy 模型（runs、kb、assets/tickets）
├─ agent/             状态机、规则节点、运行时（事件流）
├─ tools/             MCP 工具 + 治理（ToolSpec / ToolGuard）
├─ gateway/           模型网关（W4）
├─ rag/               解析、切分、分词、embedding、混合检索、pgvector 持久化
├─ seed/              50 篇知识库 + 200 资产 + 500 工单生成器
└─ eval/              20 条评测用例与 markdown 报告执行器

migrations/           Alembic
├─ env.py             DSN 取 ONCALL_DATABASE_URL
└─ versions/          0001 runs/events · 0002 幂等键作用域 · 0003 kb + assets/tickets
```

## 启动

```bash
uv sync --extra dev --extra rag   # rag = pypdf + python-docx；只跑单测可不装
uv run alembic upgrade head
uv run python -m app.seed.generate --db
uv run uvicorn app.main:app --reload --port 8000
```

评测（不依赖数据库，内存知识库）：

```bash
uv run python -m app.eval.runner
```

## 当前实现状态

| 模块 | 状态 |
|---|---|
| `main.py` / `api/health.py` | ✅ 可用（探 db + redis） |
| `api/chat.py` | ✅ 真实运行时驱动事件，逐条落库（W1 D5 + W2 retrieve） |
| `api/runs.py` | ✅ Postgres + `after_seq` / `Last-Event-ID` 补拉，只能读自己的 run |
| `api/admin_kb.py` | ✅ 上传/列表/详情/重建索引；要求 admin 角色 |
| `core/store.py` | ✅ `RunStore` Protocol + Postgres/内存两种实现 + 事件投影 |
| `migrations/` | ✅ 0001–0003，`alembic check` 无漂移 |
| `api/deps.py` / `core/security.py` / `cli.py` | ✅ 本地 JWT（W1 D2）：签发、Bearer 校验、401 JSON、run 归属 |
| `tools/registry.py` | ✅ 五道闸门、超时、重试、审批标记已实现 |
| `tools/builtin.py` | ✅ `query_cmdb` / `create_ticket` 假实现，走同一套治理（W3 换 MCP） |
| `agent/*` | ✅ `runtime.py` + `nodes/*`（intake/retrieve/plan/act/finalize）；`graph.py` 仍占位（W3） |
| `rag/*` | ✅ 解析/切分/分词/哈希或 HTTP embedding/混合检索/RRF/阈值/引用（W2） |
| `seed/*` | ✅ 50 文档 + 200 资产 + 500 工单；`--db` 索引进 pgvector |
| `eval/*` | ✅ 20 条 v0 + markdown 报告 + baseline 对比 |
| `gateway/*` | 🚧 W4 |

## 约定

- `api/` 不放业务逻辑，不写 SQL
- 事件类型只在 `schemas/event.py` 定义，前端从 OpenAPI 生成
- 工具治理只在 `tools/registry.py` 实现，**不要在 MCP server 里重复校验**
- 向量 SQL 只在 `rag/repository.py`，节点只依赖 `Retriever` 协议
- 所有时间戳 UTC；成本单位分
