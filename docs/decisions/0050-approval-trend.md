# ADR-0050：审批统计的按日趋势与时间窗口

- 状态：已采纳
- 日期：2026-11-13
- 相关：[ADR-0048](0048-approval-stats.md)（审批积压与等待统计）

## 1. 背景

ADR-0048 的 `GET /approvals/stats?days=` 已经支持 1–90 天，但前端把窗口写死为 7 天，
响应也只有窗口汇总。审批人看不到「哪天压得多、哪天的决议等得久」，也判断不了积压是
今天突发还是持续了好几天。

## 2. 备选方案

| 方案 | 取舍 |
|---|---|
| 前端按审批列表自己聚合 | 列表 `limit` 最多 200、没有 `resolved_at` 过滤，分不清「没有积压」和「没加载完」，否决 |
| 单独加 `/approvals/trend` 接口 | 同一份统计拆成两个请求、两套 loading/error，前端还要对齐窗口，否决 |
| 新增日统计表 + 定时任务 | 只读报表不值得多一张表与写路径，也会引入「统计落后」问题，否决 |
| 在现有 stats 响应里加 `daily` | 一次请求、同一窗口与鉴权口径，采纳 |

## 3. 决策

1. `ApprovalStats` 增加 `daily: tuple[ApprovalDayStats, ...]`；
   `ApprovalDayStats(day: date, decided_count: int, avg_wait_ms: int | None)`。
2. 按 **UTC 日期**分桶，只包含窗口内真正有决议的日期；**稀疏、不补零**。滚动窗口的
   `since` 不是日历日边界，补零会造出「窗口外半天」的假数据。
3. 只统计 `approved` / `rejected`，与 `decided_count` 口径一致；`expired` 不进日趋势。
4. 存储层一次聚合：内存遍历时按 `resolved_at.date()` 分桶；Postgres 用
   `date_trunc('day', timezone('UTC', resolved_at))` + `GROUP BY`（显式转 UTC，避免受会话
   时区影响），与窗口汇总在同一次 `stats()` 调用返回。
5. API 响应加 `daily`；`day` 为 `YYYY-MM-DD`，`avg_wait_ms` 只在脏数据时为空。
6. 前端提供 7/30/90 天切换，`days` 与 `daily` 使用同一个窗口；趋势卡只列文本行
   （日期 / 单数 / 平均等待），不引入图表依赖。
7. 无迁移、无新索引；不按审批人/工具分组、不告警、不缓存。
8. 仍只对审批人开放；不返回 `resolved_by`。

## 4. 后果

- 统计响应最多多 90 行日期，体积可接受；日粒度足够回答「积压是不是持续」。
- 前端不再写死 7 天，README 与 docs/03 的边界同步为 7/30/90。
- `daily` 仍是请求时快照，页面停留期间不会自动更新（与 ADR-0048 一致）。
- 按日聚合依赖 `resolved_at`，仍没有单独索引；审批量到十万级再评估。
- 时区固定 UTC：跨时区部署时「今天」与本地日历不一致，留到待定。

## 5. 验证

- 默认 **479 passed + 36 skipped**；真实 Postgres **512 passed + 3 skipped**；
  Postgres + Redis **515 passed**。
- `ruff check` / `ruff format --check`（187 files）/ `mypy app`（110 files）通过。
- 前端 `tsc`、**73 tests / 15 files**、`oxlint` 0/0（66 files、231 rules）、
  `oxfmt --check` 74 files、`pnpm build` 300ms。
- PG 用例覆盖：同一天的一条已决议审批 → `daily` 一个桶、`decided_count=1`、
  `avg_wait_ms` 与窗口汇总一致；内存用例覆盖两条决议落在同一 UTC 日。

## 6. 待定

- 按审批人/工具分组、按小时趋势；
- 积压阈值告警；
- 可配置时区（当前固定 UTC）；
- 长期趋势存储与导出。
