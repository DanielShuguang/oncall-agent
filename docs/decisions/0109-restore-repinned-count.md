# ADR-0109：恢复审计记录恢复置顶数

## 背景

[ADR-0108](0108-hidden-restore-pin.md) 让已移除会话在恢复时按当前容量尽力恢复置顶。
恢复审计（[ADR-0059](0059-session-restore-audit.md)）仍只记 `requested_count` /
`restored_count`，管理员看不出一次恢复里有多少会话真的回到了置顶区；容量不足时
「恢复成功但没置顶」与「当时本来没置顶」也无法区分。

## 备选方案

| 方案 | 不采纳原因 |
|---|---|
| 只在前端根据恢复结果猜 | 恢复响应没有逐条置顶状态；刷新后也不可追溯 |
| 在 `session_ids` 里存对象 | 破坏现有 JSONB 数组契约与 GIN `@>` 查询；历史数据难兼容 |
| 每次恢复写 `session_pin_audits` | 恢复触发的置顶不是用户显式操作，会污染置顶审计 |
| 新增独立恢复置顶表 | 一次恢复一行已存在，多一列足够；不增加连接/清理面 |

## 决策

1. `session_restore_audits` 增加 `repinned_count INTEGER NOT NULL DEFAULT 0`，
   CHECK `0 <= repinned_count <= restored_count`。
2. 值来自恢复路径容量分配后的实际插入数，不是 `was_pinned` 的数量；容量不足时
   小于 `restored_count`。恢复触发的置顶仍不写 `session_pin_audits`。
3. 管理员列表 JSON、CSV 导出和审计页都展示该列；CSV 列插在 `restored_count`
   之后，旧消费方需按表头而不是列号解析。
4. 旧审计行无法回填，统一为 0；这次不追溯历史。迁移 `0028` 只加列与 CHECK，
   downgrade 删列。
5. 不新增端点、不改恢复响应、不改保留期；统计口径仍以恢复操作/会话数为主，
   `repinned_count` 只作审计明细。

## 后果

- 管理员能看出「恢复成功但容量不足未置顶」与「当时未置顶」的差异；旧行显示 0。
- 一次恢复的 `repinned_count` 依赖瞬时的 `pin_limit` 与竞态；advisory lock 保证
  同一用户串行，但事后不能还原当时容量。
- 恢复路径多一次计数，不增加查询往返；审计仍与删除同事务。
- CSV 多一列，属于契约扩展；管理页表格多一列。

## 验证

- 默认：`534 passed + 42 skipped`；PG-only：`573 passed + 3 skipped`；
  PG+Redis：`576 passed`。
- `ruff check` / `ruff format --check` 210 files / `mypy app` 119 files 通过。
- 前端未改逻辑，仅多一列：29 files / 149 tests。
- 迁移 `0028` 往返：`upgrade head → alembic check → downgrade 0027 → upgrade head`。
- 用例：`test_store_contract.py::_exercise_restore_pin` 断言批量恢复的
  `repinned_count` 与容量不足的 0；`test_admin_sessions.py` 列表/CSV 断言新字段。

## 待定

- 是否给前端「已恢复但未置顶」的逐条提示；当前只显示数量。
- 是否在统计卡里增加「恢复置顶数」汇总。
