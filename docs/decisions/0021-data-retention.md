# 0021 · 数据保留：过期事件按 run 整场清理，runs 摘要继续保留

- 状态：已采纳（W6 后加固）
- 日期：2026-11-10
- 相关：[docs/02-data-model.md](../02-data-model.md)、[docs/03-api-contract.md](../03-api-contract.md)、[docs/07-frontend-design.md](../07-frontend-design.md)、[docs/09-deploy-private.md](../09-deploy-private.md)、[ADR-0016](0016-approval-decision-transaction.md)、[ADR-0017](0017-stale-run-recovery.md)、[ADR-0020](0020-multi-turn-context.md)

## 背景

docs/02 §4 从 W2 起就有一张保留表：`run_events` 30 天、`model_calls` 180 天、
附件 30 天。但**只有配置项、没有执行者**：

- `ONCALL_EVENT_RETENTION_DAYS` 在 `core/config.py` 里从未被读取，是死配置；
- `run_events` / `model_calls` 只增不删，私有化部署里"数据不出内网"之后
  必须回答的"数据留多久"没有答案；
- 文档自身还互相矛盾：docs/02 说事件 30 天，docs/09 §9 安全清单要求
  「审计日志保留 180 天」——`run_events` 就是审计日志，两个数字不可能同时成立；
- 保留表里的「附件 / 上传文件」在库里没有对应表：上传文件解析完就写
  `kb_documents` / `kb_chunks`，不单独落盘，这一行是 W2 的设想，从未兑现。

现在补执行者，并且必须在动手前定清楚：删什么、以什么时间为界、删完 API 怎么表现。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 按事件时间逐条删（`DELETE ... WHERE created_at < cutoff`） | 回放会从中间开始：前端归约器拿不到 `run.started`，时间线缺头，`seq` 从 17 开始；等于制造"半个 run" |
| 直接删 `runs` 行（FK 级联事件、审批、计量） | 运行列表、成本口径、失败率与多轮上下文（ADR-0020 读 `runs.input/output`）全部丢；审批决议审计也一起没；run 级保留是另一个决策，没定之前不能连带删 |
| 只加监控、不清理 | 合规问题仍在；磁盘随使用量线性增长，私有化现场没人敢跑 `DELETE` |
| 归档到冷存储 / 对象表再删 | 私有化组件与运维成本上升；v1 没有对象存储，见 ADR-0011/0015 的取舍 |
| 定时任务 + 按 run 整场删事件 + 写标记 | 回放语义完整（要么全有要么全无）、幂等、可控批次、可 dry-run；删的是"已经不看的旧回放"，不是运行摘要 |

## 决策

新增 `app/runs/retention.py: RetentionSweeper`，只做执行，策略写在这里。

### 1. 事件：按 run 整场清理，同事务写标记

- 候选条件：`status IN ('completed','failed','interrupted')` **且**
  `finished_at IS NOT NULL AND finished_at < now - ONCALL_EVENT_RETENTION_DAYS`
  **且** `events_pruned_at IS NULL`。
- 一次选中最多 `ONCALL_RETENTION_BATCH` 场 run，`DELETE FROM run_events WHERE run_id IN (...)`，
  同一事务内 `UPDATE runs SET events_pruned_at = now()`。删除与标记要么都成功，要么都回滚。
- `SELECT ... FOR UPDATE SKIP LOCKED`：多副本同时清理各拿各的批次，不互相等待；
  标记写入后下一轮不会再选中同一场 run。
- **非终态 run 永远不清理**：等待审批的 run 可能长时间没有新事件，不能被当成"旧数据"。
- `finished_at IS NULL` 的终态 run 不清理（防御性：拿不到结束时间就不猜），
  运维可按 `status + finished_at IS NULL` 排查异常数据。
- 为什么按 run 而不是按事件时间：回放是一致性读模型。只删一半，`GET /runs/{id}/events`
  会返回从 `seq=17` 开始的事件流，前端得到一条没有开头的 run；按 run 删除让
  "回放可用 / 不可用"变成二值，标记让不可用状态可解释。

### 2. 计量：只删 `model_calls`，不动 `runs` 汇总

`model_calls` 按 `created_at < now - ONCALL_MODEL_CALL_RETENTION_DAYS` 分批删，
仍用 `SKIP LOCKED`。`runs.token_in/token_out/cost_cents` 是当时累加的历史账，不跟着改：

- 保留期内 `runs.token_in == sum(model_calls.token_in)` 继续成立（test_metrics_pg 的断言）；
- 超出保留期后两者不再对账，这是"只保留汇总、不保留明细"的语义，不是账不平。
  成本看板天然按时间范围查询，查不到 180 天前的明细是预期行为。

### 3. 保留期：事件 180 天、计量 180 天

事件默认从 30 天改成 **180 天**，与 docs/09 §9 的审计要求对齐（30 与 180 的冲突
在背景里已说明）。`run_events` 同时承担回放与审计两个职责，180 天是两者的公共下限；
现场要更久就调 `ONCALL_EVENT_RETENTION_DAYS`，代价是事件表线性增长。

### 4. 不清理的数据

| 数据 | 原因 |
|---|---|
| `runs` | 运行列表、失败率、成本口径与多轮上下文都依赖；`input/output` 是产品数据，不是日志 |
| `approvals` / `approval_grants` | 审批决议是治理证据，量小；保留期未定 |
| `kb_documents` / `kb_chunks` | 知识库由管理员维护，删除是业务操作，不是保留策略 |
| 上传的原始文件 | v1 不落盘（解析后只入 `kb_documents`），没有可清理的附件表；docs/02 §4 的这一行本次删除 |

### 5. 触发方式

- API 进程 lifespan 后台任务，每 `ONCALL_RETENTION_INTERVAL_S`（默认 6 小时）扫一次；
- 运维命令 `make prune` / `python -m app.cli prune [--dry-run] [--limit N]`，
  先 dry-run 看候选；`--limit` 覆盖单批上限，用于压小批次观察负载。

启动即扫一次（不是等 6 小时），首轮就把存量过期数据收敛；失败只记
`retention_sweep_failed` 日志，不让后台任务炸掉进程。

### 6. API 与前端表现

- `GET /runs/{id}` 与 `GET /runs` 的 summary 增加 `events_pruned_at`（可空，
  只加字段，旧客户端忽略即可）；
- `GET /runs/{id}/events` 对已清理的 run 返回 **200 + 空数组**（run 存在、
  `run_status` 仍可读），不返回 404：run 没有消失，只是事件按策略删了。
  代价是单看这个接口分不清"没有事件"与"清理过"，所以由详情接口的标记负责解释；
  这样补拉接口不必为每次轮询多查一列；
- 回放页（`/runs/:id`）在 `events_pruned_at` 有值时显示"事件已过保留期被清理"，
  时间线/工具调用显示"不可用"，运行摘要、模型计量、失败归因照常展示，
  最终回答从 `run.output` 兜底展示（引用角标不可用）；
- `event_count` 变成"当前仍保留的事件数"，清理后为 0；这是保留语义的直接结果，
  不用历史计数列兜底（没有需求要"曾经有多少条事件"）。

## 后果

**收益**

- 保留期从文档承诺变成可执行、可 dry-run、可审计的运维动作；
- 磁盘增长有上限：事件 ≈ 每 run 24 条，按日均 run 数 × 180 天估算；
- 回放语义保持二值：要么完整回放，要么明确"已清理"，不会出现半个 run；
- 成本口径分两层：保留期内明细可核对，超出后仍有 `runs` 汇总。

**代价与已知风险**

- 超过 180 天的 run 只能看摘要，不能看步骤/工具调用/原始事件；需要长期回放的
  现场必须调大保留期或接受归档方案（未做）。
- `run_events` 是"审计日志"，180 天是默认值，不是合规承诺；等保/行业要求更长时
  只能改配置，没有冷归档。
- 清理任务没有压测：单批 200 场 run、6 小时间隔是保守默认值，没有测量对
  在线请求的影响；大表上 `DELETE` 会产生 WAL 与 vacuum 压力，现场应先用
  `prune --dry-run --limit` 观察再放量。
- 多副本同时清理是安全的（SKIP LOCKED + 标记同事务），但没有测试并发下的
  批次分配；数据库层面由行锁保证不重复删除。
- 删事件不影响多轮上下文：`recent_turns` 只读 `runs.input/output`（ADR-0020）。
  反过来说，**角色被撤销后的旧回答仍在 `runs.output` 里**，本次没有解决；
  按当前可见性回收内容需要重算引用文档可见性，属于 run 级保留，见待定。
- `model_calls` 删除后，`runs` 的 token/cost 与明细不再对账；成本页按日期聚合，
  历史区间会变小（查不到已删明细），这是"保留"的预期表现，但要在看板上说明。
- 已清理的 run 如果被后续事件写回（正常路径不存在：终态 run 不接受审批恢复），
  `seq` 会从 1 重新开始。当前只由 `append_event_in_session` 写入，而它只被
  审批恢复/回收调用，这两条路径都只处理非终态 run；不额外加防护。

**待定**

- 事件冷归档（对象存储 / 归档表），满足"超过 180 天仍要能看"的现场
- run 级保留：`runs.input/output` 的保留期，以及角色撤销后如何回收历史内容
- 审批记录（`approvals` / `approval_grants`）的保留期
- 清理任务的性能基线：单批耗时、对 Postgres autovacuum 的影响

## 验证

- `tests/test_retention.py`：整场删除与标记、未到期不删、非终态不删、dry-run 不动数据、
  幂等与批次、计量按时间删、阈值来自配置、非法 `limit` 拒绝。
- `tests/test_store_contract.py` 新增 `_exercise_prune`：内存与 Postgres 共用同一组断言
  （未到期不动、dry-run 只列候选、删除后 `events_pruned_at` 有值且 `event_count=0`、
  事件删了多轮上下文仍可读、重复清理不再选中）。
- `tests/test_runs_api.py`：清理后详情带 `events_pruned_at`、`output` 仍返回、
  事件接口 200 + 空数组、列表同字段。
- `tests/test_metrics_pg.py`：`prune_calls` 只删过期行、dry-run 不删、`runs` 汇总不变。
- `tests/test_config.py`：保留天数 / 间隔 / 批次配 0 在启动期拒绝；默认 180 天。
- 迁移 0010 已 `downgrade → upgrade` 往返，`alembic check` 无漂移；
  `python -m app.cli prune --dry-run` 在开发库上返回候选与截止时间。
