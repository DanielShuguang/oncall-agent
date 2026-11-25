# ADR-0136：恢复审计统计按日增加「未恢复置顶数」

## 背景

ADR-0125 给 `GET /api/admin/session-restores/stats` 的 `daily` 增加了 `repinned`，
但「当天恢复了会话、却因为原本未置顶或容量不足而没有恢复置顶」的数量只能由前端用
`sessions - repinned` 计算。管理页统计卡、CSV 导出和第三方调用方各自推导，会出现口径
漂移；而这两个字段天然满足：

```text
sessions = repinned + unrestored
```

## 备选方案

| 方案 | 结论 |
|---|---|
| 前端继续用 `sessions - repinned` 派生 | 可行，但导出 CSV 与 API 调用方要各自再算一次 |
| 只加窗口总 `unrestored` | 能看到总量，但按日趋势仍需前端再减 |
| 在 `daily` 同时返回 `repinned` 与 `unrestored` | 采纳；一次查询、一个口径，CSV 可直接透视 |

## 决策

1. `SessionRestoreAuditDayStats` 增加 `unrestored`，含义是当天所有恢复操作中
   `restored_count - repinned_count` 之和，即「恢复但未置顶」的会话数。
2. 内存与 PG 在同一个日聚合里计算，不额外查库；PG 使用
   `sum(restored_count - repinned_count)`，内存按日累加。
3. `SessionRestoreAuditDayOut` 与 `daily` JSON 返回该字段；旧客户端可忽略。
4. 统计 CSV 的每个日期增加 `daily,unrestored,YYYY-MM-DD,value` 行，列结构仍是
   `section,key,day,value`。
5. 不新增迁移：字段是查询派生值，不落库；`repinned_count` 与 `restored_count`
   仍是唯一事实源。
6. 不新增窗口总 `unrestored` 字段：总量可由客户端对 `daily` 求和，避免重复维护。
7. 前端最近活动日表增加「未恢复」列，直接显示服务端值，不再在前端相减。

## 后果

- 统计卡每个活动日都满足 `sessions = repinned + unrestored`，CSV 与 JSON 同口径。
- 旧记录/旧后端缺 `repinned_count` 时按 0 处理，此时 `unrestored` 等于
  `sessions`，与「当时没有恢复置顶概念」的语义一致。
- 只增加一个只读字段，不改变窗口、过滤、权限与游标。

## 验证

- 默认 `uv run pytest`：540 passed + 43 skipped。
- PG-only：580 passed + 3 skipped；PG+Redis：583 passed。
- `ruff check`、`ruff format --check` 211 files、`mypy app` 119 files。
- 恢复统计测试断言 7 天 `unrestored` 求和为 2、30 天为 3，CSV 含
  `daily,unrestored` 行且求和一致。
- 前端 39 files / 198 tests、`tsc`、`oxlint` 0/0、`oxfmt --check`、
  `pnpm build` 2957 modules。

## 待定

- 是否提供按用户/会话的「未恢复置顶」拆分；当前只按日聚合。
- 是否在窗口 summary 也加 `unrestored` 总量；当前由 `daily` 求和。
