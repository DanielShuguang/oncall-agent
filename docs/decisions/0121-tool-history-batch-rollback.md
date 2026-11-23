# ADR-0121：工具配置变更历史批量回滚

- 状态：已采纳
- 日期：2026-11-23
- 相关：[ADR-0037](0037-tool-setting-history.md)、[ADR-0112](0112-tool-setting-rollback.md)、[ADR-0113](0113-rollback-preview.md)、[ADR-0117](0117-rollback-current-preview.md)、[ADR-0120](0120-rollback-code-default.md)

## 背景

ADR-0112 支持逐条回滚，但实际排障常连续改了几次（例如先停用、再调角色矩阵），需要一次退回到「最早那次改动之前」。逐条回滚会产生多条中间历史，且用户容易点错。

## 备选方案

| 方案 | 结论 |
|---|---|
| 前端逐条调用单条回滚 | 中间状态可见、会产生多条历史，且每一步都可能被并发写入打断；不采纳 |
| 批量回滚到「最新选中记录」之前 | 只能撤销最后一次，不能覆盖连续改动；不采纳 |
| 批量回滚到「最早选中记录」之前 | 一次退回到这组改动的起点；采纳 |
| 全量恢复到某个时间点 | 需要额外时间轴/快照，超出本功能；不采纳 |

## 决策

1. 新增 `POST /admin/tools/{name}/history/batch-rollback`，请求 `{ "change_ids": [..] }`；1–50 条，`extra="forbid"`。
2. 所有 id 必须属于该工具；任一不存在返回 `404 HISTORY_NOT_FOUND`；未注册工具 404 `TOOL_NOT_FOUND`；非管理员 403。
3. 去重后按 `(changed_at, id)` 升序，目标为**最早一条的 `before`**；即一次撤销这组选中变更。
4. 目标为 `enabled=true` 但代码 `spec.enabled=false` 时 422 `TOOL_LOCKED`。
5. 当前配置已等于目标时返回 `changed=false`、`rolled_back=0`，不写历史。
6. 有变化时只追加**一条** `source="rollback"` 的历史（`before`=执行瞬间当前值，`after`=目标），不逐条写；旧记录不变。
7. 不新增表/迁移；不做任意时间点恢复、跨工具批量、异步任务。

## 后果

- 一次操作就能回到连续改动之前，但语义是「以最早选中记录的 before 为准」；如果用户只选后半段，结果不是「撤销所选每一条的净效果」。
- 回滚仍是非事务的「读当前 → 写覆盖」：并发管理写入可能让 `before` 不是紧邻上一条 `after`；这是 ADR-0037/0112 已有的边界。
- 批量操作只写一条历史，审计上能看清「谁在何时把这组改动整体退回」，但不会保留每个中间步骤。
- 不做批量预览的额外接口：前端用最早选中记录的现有预览接口，确认框只展示该目标。

## 验证

- `server/tests/test_tool_history.py::test_batch_rollback_targets_earliest_before`：
  - 先 PATCH 停用、再改角色矩阵，批量传 `[较新, 较早, 较早]`；
  - 断言 `rolled_back=2`、目标为「最早 before」、列表恢复、最新历史 `source="rollback"`；
  - 空数组 422、员工 403、未知 id 404。
- 默认 **538 passed + 42 skipped**、PG-only **577 passed + 3 skipped**、PG+Redis **580 passed**；`ruff check`、`ruff format --check` 210 files、`mypy app` 119 files 通过。
- 前端 `pnpm test` 33 files/169 tests、`tsc`、`oxlint` 0/0（148 files）、`oxfmt --check` 156 files、`pnpm build` 2950 modules 通过。

## 待定

- 批量回滚的逐条结果/部分成功（当前全有或全无）；
- 批量预览一次返回所有目标的差异；
- 跨工具批量回滚；
- 为批量操作增加独立审计事件（当前只写一条配置历史）。
