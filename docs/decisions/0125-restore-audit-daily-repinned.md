# ADR-0125：恢复审计统计的按日恢复置顶数

## 背景

ADR-0110 给恢复审计统计增加了窗口内「恢复置顶」总数，但明确不做日趋势：当时只有 `daily` 的
恢复次数与会话数，增加第三个指标会让每个日期多一行、也增加前端展示成本。ADR-0111 又在
统计卡上提示「未恢复置顶数」，用户能看到总数，却看不出是哪几天恢复时没有置顶。

恢复审计本身就是按恢复批次记录的；`repinned_count` 已经在每一行里。只要在已有的
UTC 日聚合里多求和一个字段，不新增表、不新增端点，就能让统计卡和统计 CSV 都看到
按日的恢复置顶数。ADR-0110 的「不做日趋势」在这里被本 ADR 替换。

## 备选方案

| 方案 | 取舍 |
|---|---|
| 保持只有总数 | 实现最小，但用户无法判断某天的恢复是否恢复了置顶 |
| 新增独立「按日置顶」端点 | 需要另一套窗口/过滤参数与导出，重复维护 |
| 在既有 `daily` 增加 `repinned` | 复用同一窗口、过滤与导出；只多一个整数字段，采纳 |
| 按小时拆 | 恢复审计通常按天看，小时粒度对交接班分析价值低 |

## 决策

1. `SessionRestoreAuditDayStats` 增加 `repinned: int = 0`，表示该 UTC 自然日内命中审计行的
   `repinned_count` 之和。
2. 内存实现按日同时累计恢复次数、恢复会话数与恢复置顶数；PG 的日聚合查询增加
   `coalesce(sum(repinned_count), 0)`，与总汇总使用同一个窗口/过滤条件。
3. `SessionRestoreAuditStatsOut` 的 `daily` 项增加 `repinned`，默认 0；旧客户端忽略该字段。
4. 统计 CSV 的 `daily` 每个日期增加一行 `("daily","repinned",day,value)`；列数不变，
   仍为 `section,key,day,value`。
5. 恢复审计统计卡在总数下方展示最近 7 个有恢复活动的 UTC 日期，列出恢复次数、会话数与
   恢复置顶数；不铺开 365 天，也不做图表。
6. 无迁移；`repinned_count` 仍是唯一事实源，日汇总只做求和。

## 后果

- 旧审计行的 `repinned_count` 为 0，日汇总同样为 0；无法反推「当时未置顶」还是「容量不足」。
- 日汇总的 `repinned` 之和等于窗口总 `repinned`；`restores`/`sessions` 的既有口径不变。
- CSV 每个日期从两行变为三行，读取方按 `section=daily` + `key` 过滤即可，列结构不变。
- 统计卡只展示最近 7 个活动日，长时间窗口仍以总数为主，避免把卡片拉成表格。
- 导出仍同步、无截断；不新增下载审计资源。

## 验证

- 默认 `538 passed + 42 skipped`；PG-only/PG+Redis 预期 577+3 / 580；本次无 store 迁移。
- `ruff check` / `ruff format --check` 210 files / `mypy app` 119 files。
- `test_admin_sessions.py`：7 天窗口 `daily.repinned` 之和为 0，30 天窗口为 3；统计 CSV 的
  `daily` 包含 `repinned` 行且求和为 1。
- 前端 33 files/174 tests、`tsc --noEmit`、`oxlint` 0/0、`oxfmt --check`、`pnpm build` 通过。

## 待定

- 是否把「按日恢复置顶」做成图表或 CSV 透视模板；
- 是否给 `daily` 增加「未恢复置顶数」（`sessions - repinned`）——当前由前端用两列相减得出。
