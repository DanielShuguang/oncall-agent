# 0016 · 审批决议与事件同一事务

- 状态：已采纳（W6 后加固）
- 日期：2026-11-09
- 相关：[docs/06-tool-governance.md](../06-tool-governance.md)、[docs/02-data-model.md](../02-data-model.md)

## 背景

审批链路原来是两步提交：

1. `POST /api/approvals/{id}/resolve` 在 `approvals` 表把 `pending` 原子改成
   `approved/rejected/expired`；
2. 服务层再单独调 `RunStore.append` 写 `approval.resolved`，拒绝/超时还要补一条
   `run.failed`。

R2 要求「事件先落库、再推送」，但这里事件本身在另一个事务里。进程如果在两步之间
崩溃，会留下「审批已通过、没有 `approval.resolved`、run 停在 `awaiting_approval`」
的半截状态：前端等不到终态，审批中心显示已完成，审计记录对不上。

重试 `resolve` 也救不回来：存储层的原子迁移返回 `changed=False`，服务层按幂等直接
返回首次结果，不会补写缺失的事件。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 事件先写、状态后写 | 事件写成功但状态更新失败时会宣称「已通过」，审批人看到的状态与事实相反，更危险 |
| 事务性发件箱（outbox）+ 后台投递 | 能解耦，但当前事件必须同步给 SSE，outbox 还要再做投递器与去重；为一次决议引入一条异步链路，收益不抵复杂度 |
| 定期对账任务扫「已通过但 run 未收敛」 | 只能事后补救，窗口内前端仍然卡住；且难以区分「崩溃前」与「工具已执行但事件未写」 |
| 存储层回调，把事件写进决议所在事务 | 改动集中、无新组件，事件仍走原有 `append` 逻辑（`build_run_patch` / seq 分配） |

## 决策

`ApprovalStore.resolve` 增加一个 `on_resolved` 回调，只在本次真的完成
`pending → status` 迁移后调用：

- **Postgres 实现**：回调在决议的同一事务内、提交前执行，收到当前 `AsyncSession`；
  服务层用 `append_event_in_session` 写 `approval.resolved` 与拒绝/超时的
  `run.failed`。任一事件写失败，事务回滚，审批仍是 `pending`，客户端可以重试。
- **内存实现**：没有事务，回调收到 `None`，服务层退回逐条 `RunStore.append`；
  仅用于测试与显式内存后端，不承诺原子性。

事件写入逻辑没有复制：`PostgresRunStore.append` 与审批回调共用
`core/store.py: append_event_in_session`，seq 分配和 `runs` 投影只有一份。

## 后果

- 决议状态、`approval.resolved`、拒绝/超时的 `run.failed` 现在是一次提交；
  不会再有「审批完成但前端没有终态事件」的窗口。
- 同意后的**恢复执行**（`act → verify → finalize`）仍在决议事务之后逐条追加事件。
  如果进程在工具执行后、事件落库前崩溃，仍可能停在非终态；这时不能自动重试写工具
  （重试 = 可能重复开单），继续按 docs/06 §7 由运维对账，本次没有扩大解决范围。
- 事务内先锁 `approvals` 行、再锁 `runs` 行；现有链路（先 `approval.required` 再
  resolve、恢复时逐事件追加）不存在反向持锁，未发现死锁路径。

## 验证

- `tests/test_approvals_pg.py::test_pg_event_failure_rolls_back_decision`：
  让事件写入抛异常，断言审批仍为 `pending`、run 仍为 `awaiting_approval`、
  没有 `approval.resolved`。
- 内存路径由现有 `test_approve_resumes_run_and_persists_ticket`、
  `test_expired_approval_fails_run` 覆盖事件顺序与终态。
