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
  client_msg_id   TEXT UNIQUE,              -- 幂等键
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
  started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at     TIMESTAMPTZ
);
CREATE INDEX idx_runs_user_time ON runs (user_id, started_at DESC);
CREATE INDEX idx_runs_status    ON runs (status) WHERE status IN ('running','awaiting_approval');
```

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

### 2.3 approvals

```sql
CREATE TABLE approvals (
  id          UUID PRIMARY KEY,
  run_id      UUID NOT NULL REFERENCES runs(id),
  tool_name   TEXT NOT NULL,
  args        JSONB NOT NULL,
  risk_level  TEXT NOT NULL,          -- low|medium|high
  status      TEXT NOT NULL,          -- pending|approved|rejected|expired
  requested_by TEXT NOT NULL,
  resolved_by TEXT,
  reason      TEXT,
  expires_at  TIMESTAMPTZ NOT NULL,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX uq_approval_pending ON approvals (run_id, tool_name)
  WHERE status = 'pending';
```

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
```

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
  source      TEXT NOT NULL,          -- 文件名/URL
  version     TEXT,
  checksum    TEXT NOT NULL,
  chunk_count INT NOT NULL DEFAULT 0,
  status      TEXT NOT NULL,          -- pending|indexed|failed
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE kb_chunks (
  id          BIGSERIAL PRIMARY KEY,
  document_id UUID NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
  ord         INT NOT NULL,           -- 文档内序号，用于引用定位
  heading     TEXT,                   -- 所属标题路径
  content     TEXT NOT NULL,
  page        INT,
  embedding   vector(1024) NOT NULL,  -- bge-m3 维度；用云模型时改为 1536/3072
  tsv         tsvector,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_chunks_doc ON kb_chunks (document_id, ord);
CREATE INDEX idx_chunks_tsv ON kb_chunks USING GIN (tsv);
CREATE INDEX idx_chunks_vec ON kb_chunks USING hnsw (embedding vector_cosine_ops);
```

> 引用溯源要求：`chunk_id + document_id + ord` 三者是前端"跳到原文位置"的唯一依据。

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
4. 一个 run 结束后，`runs` 的汇总字段（token/cost/step）与 `model_calls` 聚合必须相等——**W4 写一个一致性校验测试**

## 4. 保留与清理

| 数据 | 保留 | 说明 |
|---|---|---|
| run_events | 30 天 | 可配置 `ONCALL_EVENT_RETENTION_DAYS` |
| model_calls | 180 天 | 成本分析用，可归档 |
| attachments / 上传文件 | 30 天 | 不落对象存储，v1 用本地卷 |
| eval_results | 永久 | 体量小，是能力证明 |

## 5. 迁移

- 全部用 Alembic 管理，禁止手改线上表
- `alembic revision --autogenerate -m "xxx"`，**生成后人工审一遍**（autogenerate 会漏索引与 CHECK）
- 破坏性变更分两步：先加列/双写 → 再切读 → 最后删列
