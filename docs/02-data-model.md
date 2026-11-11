# 02 · 数据模型

> 原则：**事件表是唯一真相源**。业务表的当前态都可由事件重放推导；事件不可修改，只能追加。
> 唯一例外是保留策略：超过保留期的事件会被清理任务**按 run 整场删除**（§4，
> [ADR-0021](decisions/0021-data-retention.md)），删除后该 run 不可回放，但 `runs` 摘要仍在。

## 1. ER 概览

```
tools（代码注册） ──< tool_settings（环境覆盖：启用/角色）
runs ──< run_events
  │
  ├──< approvals
  └──< model_calls

user_budgets（按用户日预算覆盖；user_id 来自 JWT，无外键）
kb_documents ──< kb_chunks (embedding)
assets（模拟 CMDB）
tickets ──< ticket_events
（评测用例与结果不落库，见 §2.8）
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
  events_pruned_at TIMESTAMPTZ,            -- 事件被保留策略清理的时间（ADR-0021）
  content_pruned_at TIMESTAMPTZ,           -- 正文被保留策略清空的时间（ADR-0023）
  cited_document_ids JSONB NOT NULL DEFAULT '[]',  -- 回答引用过的文档 id（ADR-0022）
  CONSTRAINT uq_runs_user_client_msg UNIQUE (user_id, client_msg_id)
);
CREATE INDEX idx_runs_user_time         ON runs (user_id, started_at DESC);
CREATE INDEX idx_runs_user_session_time ON runs (user_id, session_id, started_at DESC);
CREATE INDEX idx_runs_retention         ON runs (finished_at) WHERE events_pruned_at IS NULL;
CREATE INDEX idx_runs_content_retention ON runs (finished_at) WHERE content_pruned_at IS NULL;
CREATE INDEX idx_runs_status            ON runs (status) WHERE status IN ('running','awaiting_approval');
```

> 实现：`server/app/models/run.py` + `server/migrations/versions/`。
> `runs` 没有 `created_at`，`started_at` 即创建时间；`status` 由事件投影写入，不接受 API 直接改。
> 幂等键按 **用户作用域**：不同用户撞 key 不会互相回放；空字符串视为未提供（迁移 0002）。
> 多轮上下文按 `(user_id, session_id, started_at DESC)` 取最近几轮（迁移 0009、[ADR-0020](decisions/0020-multi-turn-context.md)）：
> 只读 `runs` 的 `input/output` 与引用快照，不读事件；`idx_runs_user_time` 没有 `session_id` 前缀，不能替代。
> 会话列表（[ADR-0030](decisions/0030-session-list.md)）也从这些列投影：
> 按 `session_id` 分组取 `min/max(started_at)` 与 `count(*)`，标题取最早一条非空 `input`；
> 复用 `idx_runs_user_session_time` 的 `user_id` 前缀筛选，跨会话排序仍需要聚合——
> **没有 `sessions` 表，也没有新迁移**。正文按 ADR-0023 清空后标题为 `NULL`，会话仍会列出。
> `events_pruned_at` 非空表示这场 run 的事件已按保留策略整场删除（迁移 0010、
> [ADR-0021](decisions/0021-data-retention.md)）：**由清理任务写入，不是事件投影**；
> 回放不可用，摘要/回答/计量仍保留。
> `idx_runs_retention` 是部分索引，只含还没清理的 run：普通 `finished_at` 索引会从最老的
> 行开始扫，而最老的行恰好全是已清理的，每轮都要越过整个历史；标记写入后部分索引
> 立即移除条目。它只服务保留清理，不参与在线请求。
> `content_pruned_at` 非空表示正文（`input`/`output`）已被保留策略清空（迁移 0012、
> [ADR-0023](decisions/0023-run-content-retention.md)）：`input` 置空串、`output` 置 NULL，
> 状态/计量/失败归因/引用快照保持；`idx_runs_content_retention` 是它自己的部分索引——
> 事件先清，清完的行会掉出 `idx_runs_retention`，正文清理不能复用那个索引。
> `cited_document_ids` 是 `message.completed.citations[]` 的投影（迁移 0011、
> [ADR-0022](decisions/0022-run-content-visibility.md)）：读详情/事件/重放/多轮历史时
> 用它按**当前**可见性校验，引用文档不可见就隐藏正文。落在 runs 而不是只读事件，
> 是因为事件 180 天后会被整场清理，而 `output` 还留着。

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

> 保留期内只追加、不修改；超过 `ONCALL_EVENT_RETENTION_DAYS` 后由清理任务按 run
> 整场删除，并写 `runs.events_pruned_at`（§4，[ADR-0021](decisions/0021-data-retention.md)）。
> 删除前该 run 的所有事件必须一起删：只删一半会让回放从中间开始。

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
>
> `state` 只服务恢复执行：`resolved_at` 早于 `ONCALL_RUN_CONTENT_RETENTION_DAYS`
> 的已决议审批会被清空为 `{}`（§4），参数、理由与决议人保留。`{}` 不是合法快照
> （至少带 `run_id` / `node`），因此空对象就是「已回收」标记，不需要额外列
> （[ADR-0027](decisions/0027-approval-snapshot-retention.md)）。

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

工具定义是**代码**，不是数据库行：`name` / `description` / `input_schema` / `is_write` /
`timeout_ms` 都写在 `tools/builtin.py`，改 schema 必须走 code review 与治理测试
（docs/06 §2）。数据库只存本环境对默认值的覆盖，避免「代码加了工具但库里没同步」
导致工具凭空消失，也避免管理页在线改出一个绕过 `validate_args` 的入参。

```sql
CREATE TABLE tool_settings (
  name       TEXT PRIMARY KEY,        -- 与 ToolSpec.name 对应；无外键，删除工具后残留行读取时忽略
  enabled    BOOLEAN,                 -- NULL = 继承代码默认；false = 本环境禁用
  roles      JSONB,                   -- NULL = 继承；[] = 所有登录用户
  updated_by TEXT,                    -- 最后修改人（完整历史看结构化日志）
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

- 代码里 `enabled=False` 是硬边界：覆盖只能进一步收紧，不能把未就绪工具打开
- 生效规则：`enabled = code_enabled AND COALESCE(override.enabled, true)`；
  `roles = override.roles ?? code_roles`
- v1 不建 `roles` / `role_tool_permissions` 表：角色来自 JWT 字符串，矩阵页的角色目录
  由内置 `employee/approver/admin` 加 `ONCALL_ADMIN_ROLES` / `ONCALL_APPROVER_ROLES` 组成
- 覆盖读取有 2s 进程内缓存（ADR-0014）；单进程保存后立即失效，多副本最长 2s 生效
- 写操作即使角色允许，也仍需人工审批（`approvals` 表），权限矩阵不能替代审批

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
  visibility  VARCHAR(16) NOT NULL DEFAULT 'public',  -- public | roles（ADR-0019）
  allowed_roles VARCHAR(32)[] NOT NULL DEFAULT '{}',  -- visibility=roles 时生效
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_kb_documents_access CHECK (
    (visibility = 'public' AND cardinality(allowed_roles) = 0) OR
    (visibility = 'roles'  AND cardinality(allowed_roles) > 0)
  )
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

**文档级可见性**（[ADR-0019](decisions/0019-document-level-access.md)）：`public` 表示所有
登录用户可读，`roles` 表示 `allowed_roles` 与调用方角色有交集才可读；`admin`
（`ONCALL_ADMIN_ROLES`）是知识库所有者，不受这两个字段限制。CHECK 让两种解释互斥：
`public` 必须没有角色，`roles` 必须至少一个角色——否则「public 但有角色」在 SQL 与
Python 里会有两种读法。角色是 JWT 里的字符串标签，没有 `roles` 表可外键，所以角色列
只存字符串；检索时用 `allowed_roles && ARRAY[...]`（数组重叠）在 `LIMIT` 之前过滤。

实现：`server/app/models/kb.py` + `migrations/versions/20261109_0003_kb_and_business.py`
（可见性列在 `20261109_0008_kb_document_access.py`，存量文档落 `public`）。
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

评测**不落库**：用例是 `server/app/eval/cases/*.yaml`（50 条，按 fact / troubleshoot /
multihop / negative / injection 拆分），执行结果写文件：

- `server/eval-reports/report-*.md` 与 `baseline-*.json`（gitignore，本机复跑产物）
- `docs/eval/baseline-v1.md` / `classify-v1.md`（进仓库的基线）

没有 `eval_cases` / `eval_results` 表：用例需要 code review 与版本对比，文件比表更直接；
结果体量小，跑一次生成一次报告即可，不需要在线查询。自动化的回归门槛是
`make eval` 与 `docs/08` §6 的 -3pp 规则。

### 2.9 预算（user_budgets）

模型成本有三层口径（[ADR-0013](decisions/0013-model-gateway.md) /
[ADR-0026](decisions/0026-user-daily-budget.md)）：单 run、当日全局、**当日按用户**。
前两层在配置里，第三层允许按人覆盖：

```sql
CREATE TABLE user_budgets (
  user_id     TEXT PRIMARY KEY,        -- 来自 JWT 的 sub；用户目录不在本库，故无外键
  daily_cents INTEGER NOT NULL,        -- 日上限（分）；0 = 显式不限
  updated_by  TEXT NOT NULL,           -- 最后修改人（完整历史看结构化日志）
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  CONSTRAINT ck_user_budgets_daily_cents CHECK (daily_cents >= 0)
);
```

- 没有行 = 继承 `ONCALL_USER_DAILY_BUDGET_CNY`（默认 0 = 不限）；有行时覆盖优先；
  `daily_cents = 0` 是"该用户不限"，与"没有行"不同——后者的默认值可能非零
- 整表读进 `UserBudgetPolicy` 的 2s 缓存：改额度不重启，多副本最长 2s 生效
- **账本不落库**：预扣与结算在 `core/limits.py` 的 Redis（或内存）账本里，按 UTC 日过期；
  表里只存上限，花费的真相源仍是 `model_calls`（§2.4）；账本侧「今日已用」是另一个口径，
  由 `GET /admin/budgets/usage` 读快照（[ADR-0028](decisions/0028-budget-observability.md)）
- 账本的 Redis key（[ADR-0028](decisions/0028-budget-observability.md)）：全局
  `oncall:budget:{day}` / `oncall:budget:reservations:{day}`；按用户
  `oncall:budget:user:{user}:{day}` / `oncall:budget:user:reservations:{user}:{day}`；
  另有当日集合 `oncall:budget:users:{day}` 用于报表枚举用户。预扣时间戳是 reservations
  hash 里的 `<token>:ts` 字段，不新增 key；管理页只读快照，不改账本。**无迁移**
- 金额一律「分」整数（R6）；读写要求 `ONCALL_ADMIN_ROLES`（`/api/admin/budgets`）

## 3. 事件与业务表的一致性规则

1. **先写事件，再推流**：推送失败不影响数据完整性；前端靠补拉恢复
2. **业务表的当前态由事件驱动更新**，禁止直接 UPDATE 一个"说不清从哪来"的字段
3. 事件只追加，不修改；纠错用新事件（`run.failed` + 重跑）。保留策略的整场删除是唯一例外（§4）
4. 一个 run 结束后，`runs` 的汇总字段（token/cost/step）与 `model_calls` 聚合必须相等——W4 已落测试
   `tests/test_metrics_pg.py`（失败 run 也覆盖），并在 `make test` 的 Postgres 套件里执行。
   **保留期外不再对账**：超过 `ONCALL_MODEL_CALL_RETENTION_DAYS` 的计量明细会被清理，
   `runs` 上的汇总保留（[ADR-0021](decisions/0021-data-retention.md)）；这是「只留汇总」的语义。
   严格对账由 Postgres 后端保证（`gateway/meter.py` 同事务写计量行 + 增量更新 `runs`）；
   `ONCALL_STORE_BACKEND=memory` 只用于测试/无库演示，失败 run 的 token/cost 不保证与
   `model_calls` 一致（完成 run 仍由 `run.completed` 写入绝对值）。
5. **内容回收是读时判定，不改写历史**：引用文档的可见性变化只影响读接口的展示
   （详情 `output`、事件回放、多轮历史），不会 `UPDATE runs.output` 或删事件；
   范围改回去内容自动恢复（[ADR-0022](decisions/0022-run-content-visibility.md)）。
6. **按时间的正文清理是写时删除，不可恢复**：超过 `ONCALL_RUN_CONTENT_RETENTION_DAYS`
   的终态 run，`runs.input/output` 被清空并写 `content_pruned_at`（§4、
   [ADR-0023](decisions/0023-run-content-retention.md)）；它与第 5 条正交——第 5 条是
   「当前谁看不到」，第 6 条是「谁都不再留」，详情页同时成立时按第 6 条表述。

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

> `approval.resolved` 与拒绝/超时的 `run.failed` 由审批存储层在决议事务内写入
> （[ADR-0016](decisions/0016-approval-decision-transaction.md)）：`approvals.status`
> 迁移和这两条事件要么一起提交，要么一起回滚。
> 进程中断的孤儿 run 由回收任务追加一条普通 `run.failed(RUN_INTERRUPTED)`，投影规则不变，
> 没有新增表或字段（[ADR-0017](decisions/0017-stale-run-recovery.md)）。

## 4. 保留与清理

| 数据 | 保留 | 说明 |
|---|---|---|
| run_events | 180 天 | `ONCALL_EVENT_RETENTION_DAYS`；按 **run 整场**清理，`runs.events_pruned_at` 标记，同事务 |
| model_calls | 180 天 | `ONCALL_MODEL_CALL_RETENTION_DAYS`；只删计量明细，`runs` 上的 token/cost 汇总保留 |
| runs（行） | 不清理 | 运行列表、成本口径与失败率依赖它；删行会连带删审批与计量 |
| runs.input / output | 180 天 | `ONCALL_RUN_CONTENT_RETENTION_DAYS`；到期清空正文并写 `runs.content_pruned_at`，只留摘要（[ADR-0023](decisions/0023-run-content-retention.md)）；必须 `>= ONCALL_EVENT_RETENTION_DAYS` |
| approvals.state（执行快照） | 180 天 | 复用 `ONCALL_RUN_CONTENT_RETENTION_DAYS`，按 `resolved_at` 清空为 `{}`；挂起的审批永不清理；决议证据（`args` / `reason` / `status` / `resolved_by` / `resolved_at`）保留（[ADR-0027](decisions/0027-approval-snapshot-retention.md)） |
| approvals（决议行） | 不清理 | 审批决议是治理证据（批准了什么、谁批的、为什么），量小；冷归档见「待定」 |
| approval_grants | 过期即删 | `expires_at < now` 的行由清理任务删除；过期授权本来就不再生效，删行不改变授权语义（[ADR-0027](decisions/0027-approval-snapshot-retention.md)） |
| kb_documents / kb_chunks | 不清理 | 知识库由管理员维护，删除是业务操作，不是保留策略 |
| 评测报告（文件） | 永久 | 不入库，体量小，是能力证明（§2.8） |

> 执行者是 `app/runs/retention.py: RetentionSweeper`（[ADR-0021](decisions/0021-data-retention.md)）：
> 后台每 `ONCALL_RETENTION_INTERVAL_S`（默认 6 小时）扫一轮：单批 `ONCALL_RETENTION_BATCH`
> （默认 200 行），轮内最多 `ONCALL_RETENTION_MAX_BATCHES`（默认 10）批，取不满一批即停，
> 跑满上限会记 `retention_backlog_remaining` warning；`prune --dry-run` 只预览第一批。
> 也可手动 `make prune` / `cd server && uv run python -m app.cli prune --dry-run`。
> 只清终态（completed / failed / interrupted）且 `finished_at` 早于阈值的 run；挂起审批、
> 正在跑的 run 永远不清理。审批快照与过期授权不按 run 状态判断：快照看是否 pending 与
> `resolved_at`，授权看 `expires_at`（§4、[ADR-0027](decisions/0027-approval-snapshot-retention.md)）。
> **上传文件不单独落盘**（解析后写 `kb_documents` / `kb_chunks`），
> 早期文档里的「附件 30 天」没有对应表，已删除。
> 顺序是「事件 → 正文 → 审批快照 → 过期授权 → 计量」，且配置层强制正文保留期**不短于**事件保留期：
> `message.delta` / `message.completed` 里是同一段回答正文，事件还在时清 runs 等于没清
> （[ADR-0023](decisions/0023-run-content-retention.md)）。正文清理是**按时间**的删除，
> 与 [ADR-0022](decisions/0022-run-content-visibility.md) 的**按权限**回收正交：前者删了就不再回来，
> 后者改回可见范围即恢复。

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
- 当前迁移链：`0001` runs/events → `0002` 幂等键按用户作用域 → `0003` kb（pgvector/tsvector）+ assets/tickets → `0004` approvals → `0005` 会话授权按用户隔离 → `0006` model_calls + failure_category → `0007` tool_settings → `0008` 文档可见性 → `0009` 会话索引 → `0010` 事件清理标记/部分索引 → `0011` 回答引用快照 → `0012` 正文清理标记/部分索引 → `0013` 按用户日预算覆盖（`user_budgets`）

> `0003` 先 `CREATE EXTENSION IF NOT EXISTS vector`，否则 vector 类型与 HNSW 索引会失败；
> 测试库由 fixture 建扩展后再 `create_all`（扩展是库级对象，`drop_all` 不会删）。
