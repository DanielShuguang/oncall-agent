# 0027 · 审批快照与过期授权：清快照、留决议、删过期授权

- 状态：已采纳（W6 后加固）
- 日期：2026-11-11
- 相关：[docs/02-data-model.md](../02-data-model.md)、[docs/03-api-contract.md](../03-api-contract.md)、[docs/06-tool-governance.md](../06-tool-governance.md)、[docs/09-deploy-private.md](../09-deploy-private.md)、[ADR-0016](0016-approval-decision-transaction.md)、[ADR-0017](0017-stale-run-recovery.md)、[ADR-0021](0021-data-retention.md)、[ADR-0023](0023-run-content-retention.md)

## 背景

docs/02 §4 的保留表里，只有一行还写着「不清理」的理由是「量小、保留期未定」：

> `approvals` / `approval_grants`：审批决议是治理证据，量小；保留期未定。

ADR-0021 的「待定」也记着同一件事。现在 ADR-0022 / ADR-0023 把「回答正文留多久」讲完了：
到期清空 `runs.input/output`、事件整场删除。但同一段内容在审批表里还有一份：

- `approvals.state` 是**挂起瞬间的完整 AgentState**：用户问题（`query` / `context_query`）、
  检索命中（`retrieved`）、工具结果（`tool_results`）、计划与身份。它只在「审批通过后
  恢复执行」时被读一次（`agent/runtime.py: resume()` 从这里重放挂起的那次 `act`）。
- 决议之后这行不会再被任何路径读取，但**永久留在库里**。也就是说：正文 180 天删掉了，
  同一个问题、同一批检索证据还可以在 `approvals.state` 里原样读到——「数据留多久」这个
  问题只答了一半。
- `approval_grants` 存会话级授权，`expires_at` 过了以后 `is_granted` 已经不认，
  但行还在，随授权次数无界增长。

难点是两类数据被放在了同一行里：

1. **决议证据**（谁、何时、结论、理由、参数）是治理记录，等保/审计要看；`runs` 行本身
   永久保留（ADR-0021）就是为了让这些证据还能被解释。它不能被内容保留期带走。
2. **执行工作副本**（`state`）是同一个问题的另一份拷贝，寿命应该跟着内容走，而不是跟着
   审计记录走。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 继续不清理，把「保留期未定」留在文档里 | 正文与事件按 180 天删了，快照里还留着同一段问题与证据；保留策略只覆盖一半。`approval_grants` 仍然无界 |
| 按保留期删除整行（含决议） | 决议是治理证据，量小（只有写操作才产生），删了不可恢复；它的保留期应该比内容**长**，而快照应该比内容**短**，两者不能用同一个开关 |
| 新增 `ONCALL_APPROVAL_RETENTION_DAYS` 单独控制 | 快照里就是同一段正文与证据：配得比正文长等于自相矛盾，配得短则没有独立语义。多一个旋钮不增加表达力，只多一个配错的机会 |
| 决议时立刻清空 `state` | 审批通过后 `resume` 要读快照；进程也可能恰好崩在决议与恢复之间，人工对账要看当时参数。清理必须发生在「确定不会再恢复」之后 |
| **快照复用正文保留期清空 + 决议行永久保留 + 过期授权即删** | 见下：一份内容一个寿命，一份证据一份寿命，两类数据各按自己的语义处理 |

## 决策

### 1. 快照复用正文保留期，只清已决议的行

`RetentionSweeper` 增加一步：清空 `approvals.state`，条件是

```
status != 'pending' AND resolved_at IS NOT NULL
AND resolved_at < now - ONCALL_RUN_CONTENT_RETENTION_DAYS
AND state != '{}'::jsonb
```

- **复用正文保留期**，不新增环境变量：快照里是同一段用户问题、检索命中与工具结果；
  现场把 `ONCALL_RUN_CONTENT_RETENTION_DAYS` 调短，就是在说「这类内容只留这么久」，
  快照必须跟着短。配置层已有的「正文保留期 >= 事件保留期」校验顺带保证快照不短于事件。
- **只清非 pending**：挂起的审批还要靠快照恢复执行，也可能被人工对账查看。pending 的
  生命周期由 `expire_due`（30 秒一轮）收敛：超时 → `expired` + `run.failed(APPROVAL_TIMEOUT)`，
  之后才进入快照清理。清理本身不碰 pending，即使它很老。
- **按 `resolved_at` 而不是 `created_at`**：一条审批可能挂很久才被决议；从「不再需要快照」
  的那一刻起算，才和「正文从 run 结束起算」是同一语义。

### 2. 留什么：决议证据不动

清空 `state` 之后，下面这些列原样保留：

`args`（审批人看到的参数快照）、`risk_level`、`status`、`requested_by`、`resolved_by`、
`reason`、`scope`、`expires_at`、`created_at`、`resolved_at`。

这正是「批准了什么、谁批的、为什么」的全部证据；`GET /approvals` 本来就不返回 `state`
（docs/03 §5），所以对接口没有任何可见变化。

### 3. 不需要新列，也不需要迁移

`state` 清空后是 `{}`。**空对象本身就是「已回收」标记**：

- 合法的快照一定非空：`runtime` 在挂起时写入 `run_id`、`node`、`query` 等字段，
  空状态没法恢复执行，正常路径不会产生；
- 因此 `state != '{}'` 天然幂等，重复执行是空操作，不需要像 `runs` 那样加
  `events_pruned_at` 一类的标记列（`runs` 需要标记，是因为 `output IS NULL` 有合法含义）。

表也小：审批只在写操作挂起时产生，行数远小于事件与计量；`resolved_at` 不建索引，
与迁移 0013 的取舍一致（见「待定」）。

### 4. 过期授权按当前时间删除

`approval_grants` 中 `expires_at < now` 的行直接删除，一次最多一批：

- `is_granted` 比的是 `expires_at > at`，过期授权**本来就不再授予任何权限**，删行不改变
  判定结果，只是把无用的行清掉；
- 「谁在哪个会话授过什么工具」仍在 `approvals`（`scope='session'` 的决议行，含
  `requested_by` / `resolved_by` / `resolved_at`）与 `approval.resolved` 事件里；
- **不跟内容保留期**：它不是内容，也不是证据，是缓存；过期即无效，没有等的理由。

### 5. 执行者、顺序与收手条件

两个步骤都挂在 `RetentionSweeper` 上，与事件/正文/计量同一轮、同一批大小：

```
事件 → 正文 → 审批快照 → 过期授权 → 计量
```

- 快照放在正文之后：同一轮里先处理产品正文，再处理它的审批副本，语义上好读；
  两者互不依赖，多副本下只差一次事务。
- 「取不满一批才收手」的条件必须包含这两个计数，否则当事件/正文/计量都已经清空、
  只剩审批快照积压时，第一轮就会以为「没事了」而提前退出，积压永远清不完。
- 两个操作都幂等：快照清空后不再入选；过期授权删掉后不再存在。

### 6. 可观测

- `python -m app.cli prune` JSON 增加 `approval_snapshots` / `approval_grants`；
  `--dry-run` 给出候选数。
- 后台日志 `retention_pruned` 与 `retention_backlog_remaining` 带同名字段；
  有清理动作或触到批次上限时会出现在日志里。

### 7. 不做

- 不删审批行，不做「决议行保留期」：治理证据永久保留是显式承诺，要压缩只能冷归档（待定）。
- 不记录快照被清空的时间：`state == {}` 即状态，`resolved_at` 是决议时间，不是回收时间。
- 不归档、不导出。

## 后果

- 超过保留期的审批：参数、理由、决议人与时间仍可查，但**不能再从快照恢复执行**。这本来
  只发生在决议之前，清理永远晚于决议一个保留期。
- `resume` 不受影响：它只读「pending → approved」的快照；清理只作用于已决议且早于阈值的行。
- 清理时间不完全对齐：快照按 `resolved_at`、正文按 `finished_at`，同一场 run 的快照通常比
  正文晚一个审批 TTL 到几天（取决于审批人多晚处理），但不会比正文更早消失。
- 与 ADR-0022 正交：权限回收是读时的、可恢复的；这次是写时的、不可逆。
- 升级不需要迁移，也不需要改配置：默认按 180 天的正文保留期生效；如果现场调过
  `ONCALL_RUN_CONTENT_RETENTION_DAYS`，快照跟着它走。
- 多副本：`SKIP LOCKED` 只影响批次分配，`UPDATE state={}` / `DELETE` 都幂等，重复执行
  是空操作；没有引入新的分布式协调。
- 没有性能基准：审批表的体量按「写操作次数」算，远小于事件表，本轮没有在真实数据量上量过。

## 验证

- `tests/test_retention.py` 新增 5 条：
  - 已决议且早于正文保留期的快照被清空，`args` / `reason` / `status` / `resolved_at` 保留；
    挂起的（即使 `created_at` 很老）与未到期的都不动；
  - 阈值跟随 `ONCALL_RUN_CONTENT_RETENTION_DAYS`（调到 200 天时，90 天前的快照不清）；
  - dry-run 只计数不写，真正清理后第二轮为 0（幂等）；
  - 过期授权被删、未过期授权仍生效，第二轮不再有候选（确实是删了，而不是每轮都能数到）；
  - 只剩审批快照积压时，单轮仍会继续取批（收手条件包含新计数）。
- `tests/test_approvals_pg.py` 新增一条 Postgres 集成用例：dry-run 计数、清空后决议证据
  仍在、pending 不动、幂等、过期授权只删该删的、`is_granted` 前后一致。
- 完整回归：默认 **395 passed + 28 skipped**；接一个真实 Postgres（`pgserver` 临时实例，
  PostgreSQL 16.2 + pgvector）后 **422 passed + 1 skipped**——跳过的是 Redis 账本往返用例
  （本机没有 Redis，`ONCALL_TEST_REDIS_URL` 未设，属既有跳过量）。`ruff check` /
  `ruff format --check`（162 files）/ `mypy app`（102 files）通过；空库
  `alembic upgrade head` 一次到 0013（本轮**没有**新迁移，schema 不变）。
- 端到端：同一个临时 Postgres 上 `python -m app.cli prune --dry-run` 输出
  `"approval_snapshots": 1, "approval_grants": 1` 且不写库；真实 `prune` 后
  `state == {}`、`args` / `reason` 仍在、`approval_grants` 归零。
- 检索、提示词、`history.py` 与多轮判定未改，本轮不重跑评测（ADR-0025 的口径不变）；
  前端未改动。

## 待定

- 决议行（含 `args` / `reason`）的保留期与冷归档：当前永久保留，文档里是显式承诺。
- 是否要记录「快照已回收」的时间：`state == {}` 够用；若审计要问「哪天清掉的」，
  需要加一列或写审计日志。
- `args` 里可能含用户正文（工单标题/描述）：它与 `runs` 正文的保留期是否应该一致，
  牵涉「审批证据 vs 产品正文」的边界，留到接真实工单系统后再定。
- 审批表的清理性能与索引：按当前体量不建 `resolved_at` 索引，真实数据量下需要量一次。
- 撤销的角色/离场用户的审批记录：当前只按时间清快照，不按人删；等接 IdP 后再统一处理
  数据主体请求（与 ADR-0026 的租户维度同属一类待定）。
