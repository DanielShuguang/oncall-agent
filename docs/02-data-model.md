# 02 · 数据模型

> 原则：**事件表是唯一真相源**。业务表的当前态都可由事件重放推导；事件不可修改，只能追加。

## 1. ER 概览

```
users ──< user_roles >── roles ──< role_tool_permissions >── tools
                                                             │
runs ──< run_events                                    tools 由 MCP server 注册
  │
  ├──< approvals
  └──< model_calls

kb_documents ──< kb_chunks (embedding)
assets（模拟 CMDB）
tickets ──< ticket_events
eval_cases ──< eval_results
```

## 2. 表定义

### 2.1 runs（一次会话执行）

```sql
CREATE TABLE runs (
  id              UUID PRIMARY KEY,
  client_msg_id   TEXT,                     -- 幂等键，与 user_id 联合唯一
  user_id         TEXT NOT NULL,
  session_id      TEXT NOT NULL,
  status          TEXT NOT NULL,            -- running|awaiting_approval|completed|failed|interrupted
  intent          TEXT,
  model           TEXT,
  input           TEXT NOT NULL,
  output          TEXT,
  step_count      INT  NOT NULL DEFAULT 0,
  max_steps       INT  NOT NULL DEFAULT 12,
  token_in        INT  NOT NULL DEFAULT 0,
  token_out       INT  NOT NULL DEFAULT 0,
  cost_cents      INT  NOT NULL DEFAULT 0,  -- 分为单位
  error_code      TEXT,
  failure_category TEXT,                    -- model|tool|approval|limit|internal（W4）
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at     TIMESTAMPTZ,
  CONSTRAINT uq_runs_user_client_msg UNIQUE (user_id, client_msg_id)
);
CREATE INDEX idx_runs_user_time ON runs (user_id, started_at DESC);
CREATE INDEX idx_runs_status    ON runs (status) WHERE status IN ('running','awaiting_approval');
```

> 实现：`server/app/models/run.py` + `server/migrations/versions/`。
> `runs` 没有 `created_at`，`started_at` 即创建时间；`status` 由事件投影写入，不接受 API 直接改。
> 幂等键按 **用户作用域**：不同用户撞 key 不会互相回放；空字符串视为未提供（迁移 0002）。

### 2.2 run_events（事件，只追加）

```sql
CREATE TABLE run_events (
  run_id     UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  seq        BIGINT NOT NULL,               -- 单 run 内从 1 递增
  type       TEXT NOT NULL,                 -- 见 03-api-contract
  payload    JSONB NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, seq)
);
CREATE INDEX idx_events_type ON run_events (run_id, type);
```

`seq` 生成：`INSERT ... SELECT COALESCE(MAX(seq),0)+1 FROM run_events WHERE run_id=$1`（同事务内加行锁），或使用 `pg_sequence` + 每 run 一个序列。**不要用时间戳排序**。

> 实现选择：`SELECT ... FROM runs WHERE id=$1 FOR UPDATE` 锁住 run 行，再 `MAX(seq)+1`，与插入同事务。
> 一个 run 只有一条写入流，串行成本可忽略；不需要为每个 run 建序列（见 ADR-0009）。

### 2.3 approvals

```sql
CREATE TABLE approvals (
  id          UUID PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  call_id     TEXT NOT NULL,          -- 挂起的那次工具调用，恢复执行时复用
  session_id  TEXT,                   -- scope=session 的授权维度
  tool_name   TEXT NOT NULL,
  args        JSONB NOT NULL,         -- 审批人看到的参数快照
  risk_level  TEXT NOT NULL,          -- low|medium|high
  status      TEXT NOT NULL,          -- pending|approved|rejected|expired
  requested_by TEXT NOT NULL,
  resolved_by TEXT,
  reason      TEXT,
  scope       TEXT NOT NULL DEFAULT 'once',   -- once|session
  state       JSONB NOT NULL DEFAULT '{}',    -- 挂起瞬间的 AgentState 快照
  expires_at  TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_approval_pending ON approvals (run_id, tool_name)
  WHERE status = 'pending';
CREATE INDEX idx_approvals_pending ON approvals (status, expires_at);

-- scope=session 的授权；过期后自然回到逐次审批
-- user_id 必须在主键里：session_id 由客户端传入，只按 (session, tool) 授权
-- 会让别人复用同一 session_id 继承授权
CREATE TABLE approval_grants (
  user_id     TEXT NOT NULL,
  session_id  TEXT NOT NULL,
  tool_name   TEXT NOT NULL,
  granted_by  TEXT NOT NULL,
  expires_at  TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, session_id, tool_name)
);
```

> `state` 是审批恢复的关键：审批通过后只重放挂起的那次 `act`，不重跑
> `intake/retrieve/plan`。否则等待审批期间知识库或工具配置一变，
> 审批人看到的参数就与真正执行的参数不一致了（docs/06 §7）。

### 2.4 model_calls（计量）

```sql
CREATE TABLE model_calls (
  id          BIGSERIAL PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
  step        TEXT NOT NULL,          -- 节点名
  provider    TEXT NOT NULL,          -- cloud|local
  model       TEXT NOT NULL,
  token_in    INT NOT NULL,
  token_out   INT NOT NULL,
  cost_cents  INT NOT NULL,
  latency_ms  INT NOT NULL,
  first_token_ms INT,
  status      TEXT NOT NULL,          -- ok|error|fallback
  error       TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_model_calls_day ON model_calls (created_at);
CREATE INDEX idx_model_calls_run ON model_calls (run_id);
```

> 实现（W4 D18）：`server/app/models/model_call.py` + 迁移 `0006`。
> 每行是一次真实 provider 调用；失败尝试也留痕（`status=error`、token 记 0），
> 成功切换 provider 的那一行记 `status=fallback`。
> **`runs.token_*`/`cost_cents` 由 `gateway/meter.py` 在写这一行时同事务增量更新**，
> 而不是等 `run.completed` 才结算：失败、超时、审批拒绝的 run 不会走到完成事件，
> 只在完成时结算会少统计。`run.completed.payload` 里的 totals 仍会写一次绝对值，
> 与增量累计相等，用于事件回放侧展示。
> 价格单位是「分 / 百万 token」（配置项 `ONCALL_CLOUD_PRICE_*_CENTS_PER_1M`），
> 成本向上取整到分；本地模型默认为 0。

### 2.5 tools / roles / 权限矩阵

```sql
CREATE TABLE tools (
  name        TEXT PRIMARY KEY,        -- 唯一工具名，模型只能填这个名字
  description TEXT NOT NULL,
  input_schema JSONB NOT NULL,
  server      TEXT NOT NULL,           -- 所属 MCP server
  is_write    BOOLEAN NOT NULL DEFAULT false,
  timeout_ms  INT NOT NULL DEFAULT 3000,
  enabled     BOOLEAN NOT NULL DEFAULT true
);

CREATE TABLE roles (id TEXT PRIMARY KEY, name TEXT NOT NULL);

CREATE TABLE role_tool_permissions (
  role_id   TEXT NOT NULL REFERENCES roles(id),
  tool_name TEXT NOT NULL REFERENCES tools(name),
  PRIMARY KEY (role_id, tool_name)
);
```

### 2.6 知识库

```sql
CREATE TABLE kb_documents (
  id          UUID PRIMARY KEY,
  title       TEXT NOT NULL,
  source      TEXT NOT NULL,          -- 文件名/URL；同 source 再上传会覆盖
  version     TEXT,
  checksum    TEXT NOT NULL,          -- 标题 + 正文的 sha256，用于判断是否变化
  chunk_count INT NOT NULL DEFAULT 0,
  status      TEXT NOT NULL,          -- pending|indexed|failed（v1 只写 indexed）
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE kb_chunks (
  id          BIGSERIAL PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  ord         INT NOT NULL,           -- 文档内序号（1 起），用于引用定位
  heading     TEXT,                   -- 标题路径：打印机 > 离线排查 > 步骤 3
  content     TEXT NOT NULL,
  page        INT,                    -- PDF 页码；其他格式为 NULL
  tokens      TEXT NOT NULL,          -- 应用层分词结果（中文单字 + 二元组）
  tsv         tsvector NOT NULL,      -- to_tsvector('simple', tokens)
  embedding   vector(1024) NOT NULL,  -- 维度与 ONCALL_EMBEDDING_DIM 强一致
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON kb_chunks (document_id, ord);
CREATE INDEX idx_chunks_tsv ON kb_chunks USING GIN (tsv);
CREATE INDEX idx_chunks_vec ON kb_chunks USING hnsw (embedding vector_cosine_ops);
```

> 引用溯源要求：`chunk_id + document_id + ord` 三者是前端"跳到原文位置"的唯一依据。
> `tokens` 是应用层切分（单字 + 二元组）再喂给 `to_tsvector('simple', ...)`：
> Postgres 默认分词器会把连续汉字当成一个 token，中文 BM25 会失效（见 ADR-0011）。
> `embedding` 固定 1024 维；换 embedding 模型必须先迁移表结构，配置里改了维度会启动即拒绝。

实现：`server/app/models/kb.py` + `migrations/versions/20261109_0003_kb_and_business.py`。
W2 D8 起真实使用 pgvector HNSW + GIN；`alembic check` 无漂移。

### 2.7 业务域（模拟真实系统，可换真实接口）

```sql
CREATE TABLE assets (            -- 模拟 CMDB
  id          TEXT PRIMARY KEY,  -- 设备编号
  owner_id    TEXT NOT NULL,
  type        TEXT NOT NULL,     -- laptop|desktop|printer|server
  model       TEXT,
  location    TEXT,
  ip          TEXT,
  warranty_to DATE,
  status      TEXT               -- online|offline|repairing
);

CREATE TABLE tickets (
  id          TEXT PRIMARY KEY,
  title       TEXT NOT NULL,
  description TEXT,
  category    TEXT,              -- hardware|network|software|account
  priority    TEXT,              -- P0-P3
  status      TEXT,              -- open|in_progress|resolved|closed
  requester   TEXT NOT NULL,
  assignee    TEXT,
  asset_id    TEXT REFERENCES assets(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
```

> W2 D6：`app/seed/generate.py` 生成 200 资产 / 500 工单（含重复报修等噪声），
> `--db` 时写入这两张表；W3 让 `query_cmdb` / `create_ticket` 真正查表（当前仍是代码常量）。

### 2.8 评测

```sql
CREATE TABLE eval_cases (
  id          TEXT PRIMARY KEY,
  question    TEXT NOT NULL,
  expected    JSONB NOT NULL,       -- {must_cite:[...], must_call:[...], forbidden_tools:[...]}
  tags        TEXT[],
  difficulty  TEXT
);

CREATE TABLE eval_results (
  id          BIGSERIAL PRIMARY KEY,
  batch_id    UUID NOT NULL,
  case_id     TEXT NOT NULL REFERENCES eval_cases(id),
  run_id      UUID,
  passed      BOOLEAN NOT NULL,
  metrics     JSONB NOT NULL,       -- {recall, cite_acc, steps, cost_cents, latency_ms}
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 3. 事件与业务表的一致性规则

1. **先写事件，再推流**：推送失败不影响数据完整性；前端靠补拉恢复
2. **业务表的当前态由事件驱动更新**，禁止直接 UPDATE 一个"说不清从哪来"的字段
3. 事件只追加，不修改；纠错用新事件（`run.failed` + 重跑）
4. 一个 run 结束后，`runs` 的汇总字段（token/cost/step）与 `model_calls` 聚合必须相等——W4 已落测试
   `tests/test_metrics_pg.py`（失败 run 也覆盖），并在 `make test` 的 Postgres 套件里执行。

### 3.1 事件 → `runs` 投影

投影只做机械映射（`server/app/core/store.py: build_run_patch`），业务判断留在 runtime：

| 事件 | `runs` 变化 |
|---|---|
| `run.started` | `status=running`，写 `model` / `max_steps` |
| `step.completed` | `step_count += 1`（失败 run 也能看到跑了几个节点；`run.completed.payload.steps` 会覆盖为准确值） |
| `approval.required` | `status=awaiting_approval` |
| `approval.resolved` | `approved → running`；`rejected/expired → failed` + `error_code`（`APPROVAL_REJECTED` / `APPROVAL_TIMEOUT`），写 `finished_at`；随后还会追加一条 `run.failed`，让只消费事件的前端也能收敛 |
| `message.completed` | 写 `output` |
| `run.completed` | `status=completed`，写 `finished_at` / `step_count` / `token_*` / `cost_cents` |
| `run.failed` | `status=failed`，写 `error_code` / `failure_category` / `finished_at` |
| 其他（`heartbeat` 等） | 不改 `runs`，只追加事件 |

## 4. 保留与清理

| 数据 | 保留 | 说明 |
|---|---|---|
| run_events | 30 天 | 可配置 `ONCALL_EVENT_RETENTION_DAYS` |
| model_calls | 180 天 | 成本分析用，可归档 |
| attachments / 上传文件 | 30 天 | 不落对象存储，v1 用本地卷 |
| eval_results | 永久 | 体量小，是能力证明 |

> 保留清理任务本身尚未实现（W6 运维项）；当前只有审批超时 sweeper，
> 会自动把过期 pending 置 expired 并收敛 run。

## 5. 迁移

- 全部用 Alembic 管理，禁止手改线上表
- `alembic revision --autogenerate -m "xxx"`，**生成后人工审一遍**（autogenerate 会漏索引与 CHECK）
- 破坏性变更分两步：先加列/双写 → 再切读 → 最后删列

```bash
cd server
uv run alembic upgrade head          # 应用迁移（DSN 取 ONCALL_DATABASE_URL）
uv run alembic check                 # 模型与迁移是否漂移；CI 也跑
uv run alembic upgrade head --sql    # 无库环境渲染 DDL，评审用
```

- 迁移文件在 `server/migrations/versions/`；`alembic.ini` 只放占位 DSN，真实 DSN 由 `migrations/env.py` 从环境变量读
- 必须写 `downgrade`，并在空库上验证一次 `downgrade base && upgrade head`
- 当前迁移链：`0001` runs/events → `0002` 幂等键按用户作用域 → `0003` kb（pgvector/tsvector）+ assets/tickets → `0004` approvals → `0005` 会话授权按用户隔离 → `0006` model_calls + failure_category

> `0003` 先 `CREATE EXTENSION IF NOT EXISTS vector`，否则 vector 类型与 HNSW 索引会失败；
> 测试库由 fixture 建扩展后再 `create_all`（扩展是库级对象，`drop_all` 不会删）。
