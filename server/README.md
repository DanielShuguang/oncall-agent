# server · FastAPI + 8 节点状态机

## 目录

```
app/
├─ main.py            FastAPI 应用工厂
├─ cli.py             本地签发 JWT（`python -m app.cli token`）
├─ api/               路由（薄层：校验、鉴权、调 service）
├─ core/              配置、数据库引擎、JWT 校验、SSE 编码、存储、限流/预算
├─ schemas/           Pydantic 模型（事件契约/知识库/审批/成本）
├─ models/            SQLAlchemy 模型（runs、kb、assets/tickets、approvals、model_calls、tool_settings）
├─ approvals/         审批存储/服务（提交、决议、超时回收、恢复执行）
├─ agent/             8 节点状态机、规则节点、运行时（事件流 + 审批恢复）
├─ tools/             MCP 工具 + 治理（ToolSpec / ToolGuard）
├─ gateway/           模型网关（路由/适配/failover/计量）
├─ rag/               解析、切分、分词、embedding、混合检索、pgvector 持久化
├─ seed/              50 篇知识库 + 200 资产 + 500 工单生成器
└─ eval/              50 条评测、SSE 压测、三条剧本 demo

migrations/           Alembic
├─ env.py             DSN 取 ONCALL_DATABASE_URL
└─ versions/          0001 runs/events · 0002 幂等键 · 0003 kb + assets/tickets · 0004 approvals · 0005 授权按用户隔离 · 0006 model_calls · 0007 tool_settings
```

## 启动

```bash
uv sync --all-extras   # dev + rag（pypdf/python-docx）+ agent（可选）；未装 rag 时解析用例自动 skip
uv run alembic upgrade head
uv run python -m app.seed.generate --db
uv run uvicorn app.main:app --reload --port 8000
```

评测（不依赖数据库，内存知识库）：

```bash
uv run python -m app.eval.runner          # 50 条 RAG 评测
uv run python -m app.eval.classify        # 50 条意图分类评测（D11）
uv run python -m app.eval.loadtest        # 对运行中的 API 打 SSE 压测
uv run python -m app.eval.demo            # 三条剧本（含审批）
```

## 当前实现状态

| 模块 | 状态 |
|---|---|
| `main.py` / `api/health.py` | ✅ 可用（探 db + redis） |
| `api/chat.py` | ✅ 8 节点运行时驱动事件，逐条落库 + 用户级限流（W4） |
| `api/runs.py` | ✅ 列表/详情/补拉；`after_seq` / `Last-Event-ID`，只能读自己的 run |
| `api/admin_kb.py` | ✅ 上传/列表/详情/重建索引；要求 admin 角色 |
| `api/admin_tools.py` | ✅ 工具列表、启停、试调用、权限矩阵（W5，ADR-0014） |
| `api/cost.py` | ✅ 成本聚合（day/model/user，UTC 日期，admin） |
| `core/store.py` | ✅ `RunStore` Protocol + Postgres/内存两种实现 + 事件投影 |
| `core/limits.py` | ✅ Redis 滑动窗口限流 + 日预算（不可用时内存降级） |
| `migrations/` | ✅ 0001–0007，`alembic check` 无漂移 |
| `api/deps.py` / `core/security.py` / `cli.py` | ✅ 本地 JWT（W1 D2）：签发、Bearer 校验、401 JSON、run 归属 |
| `tools/registry.py` | ✅ 五道闸门、超时、重试、身份注入（`inject_identity`） |
| `tools/builtin.py` | ✅ `create_ticket` 审批后真写 `tickets`；`query_cmdb` 仍是假 CMDB |
| `tools/policy.py` | ✅ `tool_settings` 覆盖 + 2s 缓存；试调用与真实 run 共用 `ToolGuard` |
| `agent/*` | ✅ 8 节点（intake/classify/retrieve/plan/act/verify/approve/finalize）+ 审批恢复（ADR-0012） |
| `api/approvals.py` / `approvals/*` | ✅ 待办列表、批准/拒绝、超时回收、会话级授权、幂等 |
| `rag/*` | ✅ 解析/切分/分词/哈希或 HTTP embedding/混合检索/RRF/阈值/引用（W2） |
| `seed/*` | ✅ 50 文档 + 200 资产 + 500 工单；`--db` 索引进 pgvector |
| `eval/*` | ✅ 50 条五类评测 + 分类报告 + baseline 对比；SSE 压测；三条剧本 demo |
| `gateway/*` | ✅ OpenAI 兼容 + Ollama 适配、规则路由、failover、`model_calls` 计量（W4，ADR-0013） |

## 约定

- `api/` 不放业务逻辑，不写 SQL
- 事件类型只在 `schemas/event.py` 定义，前端从 OpenAPI 生成
- 工具治理只在 `tools/registry.py` 实现，**不要在 MCP server 里重复校验**
- 向量 SQL 只在 `rag/repository.py`，节点只依赖 `Retriever` 协议
- 审批 SQL 只在 `approvals/store.py`，runtime 只依赖 `ApprovalRecorder` 协议
- 所有时间戳 UTC；成本单位分
