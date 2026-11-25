# ADR-0132：已移除会话列表显示移除时置顶

## 背景

ADR-0108 让恢复已移除会话时按 `hidden_sessions.was_pinned` 与当前 `pin_limit` 尽力恢复置顶。
但 `GET /sessions/hidden` 只返回标题、轮数与移除时间，用户看不到「恢复后会不会重新置顶」，
尤其容量不足时只能恢复后才发现没有置顶。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 恢复后再提示 | 信息太晚，用户已经点了恢复 |
| 前端逐条查置顶列表 | 多请求、已移除会话不在置顶列表里，查不到 |
| 列表返回 `was_pinned` | 一次查询带出已有字段，不改写入、不加迁移 |

采用第三种。

## 决策

1. `HiddenSessionSummary` / `HiddenSessionOut` 增加只读 `was_pinned: bool`，默认 `false`。
2. 内存实现用 `_hidden_session_pins`；PG 直接读 `hidden_sessions.was_pinned`，与恢复逻辑同源。
3. 前端折叠区在移除时间后显示「移除时置顶（恢复按容量尽力）」；容量不足时不保证恢复置顶，
   文案不承诺一定成功。
4. 无新表、无迁移；旧记录为 `false`，表示移除时未置顶（或升级前不知道），不推断。
5. 不把「恢复后是否实际置顶」提前算进来：那取决于执行瞬间的容量与请求顺序，列表只描述历史状态。

## 后果

- 列表多一列读取，无额外查询；字段语义稳定。
- 用户能预判恢复后的置顶倾向，但实际仍以恢复结果为准。
- 旧行默认 `false` 是一次性降级，不做回填。

## 验证

- `test_store_contract.py` 的恢复置顶用例断言隐藏列表 `was_pinned is True`。
- `test_sessions_api.py` 批量移除用例断言 `sess_hide_a.was_pinned` 为 true、未置顶的为 false。
- 前端 `HiddenSessionsPanel` 在 `was_pinned` 时渲染提示；tsc/oxlint/test/build 通过。

## 待定

- 折叠区直接显示「恢复后预计置顶」需要容量快照，当前不做。
