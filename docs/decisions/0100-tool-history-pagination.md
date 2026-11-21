# ADR-0100：工具配置变更历史分页与首屏总数

- 状态：已采纳
- 日期：2026-11-20
- 相关：[ADR-0037](0037-tool-setting-history.md)、[ADR-0098](0098-tool-history-date-range.md)、[ADR-0099](0099-tool-history-export.md)

## 背景

ADR-0037 的工具配置变更历史只有 `limit`（默认 20，最多 100），按 `changed_at DESC, id DESC`
取最近 N 条。ADR-0098 增加 UTC 日期范围后，用户可以把窗口固定到某次变更，但窗口内超过
100 条时仍无法继续往下看；页面也没有总数，管理员无法判断是否还有更早的变更。

导出（ADR-0099）有独立的 5000 行硬上限，不能替代日常查看。

## 备选方案

| 方案 | 结论 |
|---|---|
| 调大 `limit` 上限 | 不采纳。一次返回更多行并不解决无限增长，只会放大单次响应 |
| 页码 / OFFSET | 不采纳。历史会继续追加，翻页时偏移会漂移，且深页查询变慢 |
| keyset 游标 `(changed_at, id)` 降序 | **采纳**。与现有排序、索引一致，翻页稳定 |
| 首屏 total + 无限滚动 | 采纳 total；前端用「加载更多」而不是无限滚动，便于停下来看 |
| 为分页新增索引 | 不采纳。现有 `(tool_name, changed_at DESC)` 已覆盖过滤与排序，`id` 仅同一时刻的 tiebreaker |

## 决策

1. **游标是 keyset**：上一页最后一条的 `(changed_at, id)`，降序取更早的记录；
   必须同时比较 `changed_at` 与 `id`，否则同一时刻的多条记录会重复或漏掉。
2. **游标绑定筛选**：base64url JSON `{t,i,f}`，`f` 是工具名 + 已应用日期窗口的 SHA-256
   前 16 hex。换工具或换日期窗口后旧游标返回 `400 INVALID_CURSOR`，不能静默跨口径翻页。
3. **首屏 total**：无游标时用 `count_history` 查一次总数；后续页为 `null`。计数与列表是
   两次查询，`total < len(items)` 时把 total 降级为 `null`，不显示矛盾数字。
4. **next_cursor 只在还有更多时给**：当前页必须取满 `limit`，且（`total` 未知或
   `total > len(items)`）。最后一页不再给游标，前端不需要多发一次空请求。
5. **limit 语义不变**：1–100，默认 20；游标只负责继续，不改变 `limit` 上限。
6. **无迁移**：排序与过滤沿用现有索引，`count_history` 走同一条件；不新增表/列。
7. **导出不受分页影响**：CSV 导出仍是一次最多 5000 行的快照，不是游标翻页；两者可复用
   日期窗口，但导出不会因为历史分页而改变行数上限。

## 后果

- **好处**：窗口内超过 100 条可继续看；管理员能看到「共 N 条」；游标不会跨工具/日期误用。
- **代价**：首屏多一次 count 查询；计数与列表非同一快照时 total 可能为 null；不提供跳页，
  只能顺序「加载更多」；客户端要保存 `next_cursor`，刷新后从头开始。
- 加载更多失败时保留已加载列表，只在底部提示；不会因一次分页失败清空已看记录。
- **不做**：页码/跳页、读取审计、游标签名（令牌只由服务端生成，伪造游标最多读到同一工具/
  窗口的公开历史，仍受管理员鉴权保护）；变更人/来源过滤由 ADR-0101 补上，游标过期由 ADR-0102 补上。

## 验证

- `test_history_paginates_and_binds_cursor_to_filters`：3 条记录，limit=2 首屏 total=3、
  ids `[3,2]` 且有 `next_cursor`；下一页 total=null、ids `[1]`、无 `next_cursor`；
  改日期窗口复用旧游标 400；`not-a-cursor` 400；超过 512 字节的游标也走 400
  `INVALID_CURSOR`，不是框架的 422。
- `test_history_counts_and_pages_by_changed_at`（PG）：`count_history` 正确，`before`
  按 `(changed_at, id)` 取到更早一条。
- 默认 532 passed + 42 skipped；PG-only 571 passed + 3 skipped；PG+Redis 574 passed。
- `ruff check` / `ruff format --check` 208 files / `mypy app` 119 files。
- 前端 27 files / 136 tests、lint 0/0（132 files）、format 140 files、build 2939 modules。

## 待定

- ~~变更人/来源过滤~~：已由 [ADR-0101](0101-tool-history-filters.md) 补上。
- 是否需要「跳到最早/最新」；当前只支持顺序加载。
- ~~游标是否需要过期时间~~：已由 [ADR-0102](0102-tool-history-cursor-expiry.md) 补上（1 小时）。
