# 0017 · 孤儿 run 回收：只收敛状态，不重放写操作

- 状态：已采纳（W6 后加固）
- 日期：2026-11-09
- 相关：[docs/06-tool-governance.md](../06-tool-governance.md)、[docs/09-deploy-private.md](../09-deploy-private.md)、[ADR-0016](0016-approval-decision-transaction.md)

## 背景

事件先落库、再推送（R2），`runs.status` 是事件投影（docs/02 §3）。这条链路有一个
前提：写事件的那个进程还活着。

进程重启、被 `kill`、容器被驱逐或机器掉电时，正在执行的 run 不会再有事件写入：

- `runs.status` 永远停在 `running`，运行列表一直显示"执行中"；
- 回放页（`/runs/:id`）等不到终态，客户端轮询 5 分钟后放弃；
- 失败率、成本看板把这次 run 当成"还没结束"，数字对不上；
- 审批通过后的恢复执行（`act → verify → finalize`）在决议事务之外，崩在中间同样会
  留下非终态 run（ADR-0016 已明确这个窗口没有消除）。

审批等待中的 run 有另一条回收路径：`expire_due` 在 TTL 后把审批置 `expired` 并写
`run.failed(APPROVAL_TIMEOUT)`。但 `running` 的孤儿此前没有任何兜底，只能人工改库。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 自动重放 `resume`，把 run 跑完 | 崩在工具执行之后时，无法判断工单是否已经创建；重跑一次写工具就是重复开单（R10 要求写操作声明幂等才允许重试），审批参数快照也可能已经过期 |
| 只 `UPDATE runs SET status='failed'`，不写事件 | 投影与事件表分叉：回放页仍会看到 run 停在最后一步，按事件统计的失败率依然不包含它 |
| 运维手动跑 SQL / 脚本 | 私有化现场没有这个能力；没有统一口径，容易漏改或改错 |
| 定期扫描 + 原子条件追加 `run.failed` | 只收敛状态、不执行工具；事件仍是唯一真相源；多副本可用行锁去重 |

## 决策

新增一个不经过 HTTP 的纯运维能力：`app/runs/recovery.py: RunRecovery.reap()`。

1. 扫描 `running` 且「最后一条事件（没有事件时用 `started_at`）早于
   `now - ONCALL_STALE_RUN_MIN`」的 run。默认阈值 **10 分钟**，远大于单 run 时长
   上限 120s（`agent/state.py: RUN_TIMEOUT_S`），正常运行的 run 不可能触发。
2. 对每个候选调用 `RunStore.fail_stale_run()`：在**同一事务**里锁 `runs` 行、
   复查状态与最后活动时间、再 `append_event_in_session(RUN_FAILED)`。候选列表与
   真正写入之间如果有新事件或 run 已结束，返回 `False`，不会误杀。
3. `run.failed` 的 `error_code` 是 `RUN_INTERRUPTED`，`category=internal`，
   payload 的 message 明确写「不会自动重试，请人工确认后重新发起」。

触发方式两处，共用同一服务：

- API 进程的 lifespan 后台任务，每 `ONCALL_RECOVERY_INTERVAL_S`（默认 60s）扫一次；
- 运维命令 `make reap` / `python -m app.cli reap [--dry-run] [--older-than-min N]`，
  用于立即处理或先看候选。

`awaiting_approval` 不归本任务管：它的终态由审批 TTL 负责（`ApprovalService.expire_due`），
提前判死会让审批人点通过时收到 `APPROVAL_NOT_READY`。

## 后果

- 进程崩溃留下的 run 最多在一个「阈值 + 扫描间隔」窗口内收敛到
  `failed(RUN_INTERRUPTED)`，列表、回放、看板拿到同一个终态。
- **写操作仍可能已经执行**：回收只写状态，不判断工单是否落库。运维要按 run_id
  查 `tickets` / 外部系统后决定是否重试；必要时人工补单，避免重复。
- 晚到的原进程如果还活着（例如卡在数据库锁上超过 10 分钟），会在 `run.failed`
  之后继续追加 `step.*` / `message.*` 事件，最终 `run.completed` 可能把状态改回
  `completed`。这种场景以"进程实际还在跑"为准；阈值远大于 run 超时，概率极低，
  不额外加 fencing token。
- 多副本同时扫描是安全的：`fail_stale_run` 用 `SELECT ... FOR UPDATE` 串行化，
  只有第一方能写入失败事件；测试覆盖了并发调用。
- 本方案不替代 ADR-0016 的事务化决议，也不做自动重放；ADR-0016 否决的是
  「自动把 run 跑完」的定期对账，不是「只收敛状态」。

## 验证

- `tests/test_store_contract.py::test_memory_store_contract` /
  `test_postgres_store_contract` 共用 `_exercise_stale`：新鲜 run 不入选、无事件 run
  用 `started_at` 兜底、重复回收不写第二条 `run.failed`、终态不再入选。
- `tests/test_recovery.py`：阈值、dry-run、审批等待不误杀、幂等、`limit` 分批、
  「最后活动时间优先于 `started_at`」、payload 口径。
- `tests/test_recovery_pg.py::test_concurrent_reap_writes_failure_once`：两个回收任务
  并发，只有一个 `run.failed`。
