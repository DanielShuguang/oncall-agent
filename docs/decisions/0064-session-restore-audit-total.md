# ADR-0064：会话恢复审计列表总数

- 状态：已采纳
- 日期：2026-11-14
- 相关：[ADR-0059](0059-session-restore-audit.md)（审计表）、
  [ADR-0060](0060-session-restore-audit-pagination.md)（keyset 分页）、
  [ADR-0061](0061-session-restore-audit-session-filter.md)（按 session 反查）、
  [ADR-0063](0063-session-restore-audit-console.md)（管理页）

## 1. 背景

`GET /admin/session-restores` 只返回当前页与 `next_cursor`，管理页只能显示
「已加载 N 条」。审计保留 365 天，管理员按用户或会话过滤后，不知道命中多少条、
还要翻几页；导出能给一次性文件，但不能替代页面上的计数。

审批列表已在 ADR-0057 用「第一页附 `total`、后续页 `null`」解决同类问题。
审计列表同样适合这个口径，且不需要页码/跳页。

## 2. 备选方案

| 方案 | 取舍 |
|---|---|
| 每页都返回 `total` | 每次「加载更多」多一次 COUNT，而总数在翻页期间通常不变；否决 |
| 单独加 `GET /admin/session-restores/count` | 页面多一个请求、多一套 loading/error；首屏还要等两个响应；否决 |
| 只在管理页用「已加载 N 条」 | 无总数，无法判断是否还有大量记录；当前痛点；否决 |
| 用导出文件的行数代替 | 多一次同步导出、可能截断到 5000 条；不是页面计数；否决 |
| 第一页附 `total`，后续页 `null` | 首屏一次请求拿到计数，翻页不重复 COUNT；采纳 |

## 3. 决策

1. `SessionRestoreAuditListResponse` 增加 `total: int | None`。只在请求**没有
   `cursor`** 时返回；后续页固定为 `null`。前端把 `null` 当「未知」，兼容旧后端。
2. 计数与列表使用同一口径：同一个 `user_id`、同一个 `session_id`、同一个管理员
   范围；内存实现复用记录遍历过滤，Postgres 用同一组 `WHERE` 条件。
3. `RunStore` 新增 `count_session_restore_audits(user_id, session_id) -> int`：
   - 内存实现遍历 `_session_restore_audits`，按用户与会话数组包含过滤；
   - Postgres 用 `SELECT count(*)`，`user_id` 走 `(user_id, restored_at)` 索引，
     `session_id` 走迁移 0020 的 `jsonb_path_ops` GIN；不带过滤时是全表 COUNT。
4. API 在 `list_session_restore_audits` 成功后、且 `cursor is None` 时调用计数；
   计数失败与列表读取失败一样返回 503 `DATABASE_UNAVAILABLE`，不用 0 冒充。
5. 计数与列表是两次查询，不是同一快照：两次查询之间新增/清理的审计会让 `total`
   与当前页略有出入；前端以列表为准，`total` 只是导航信息。刷新后重新对齐。
6. 无迁移、无新索引。全表 COUNT 可能扫描较多行；明确接受首屏成本，大数据量下
   再评估缓存/近似计数或按时间范围限制。
7. 前端首屏显示「共 N 条」；`items.length < total` 时追加「已加载 M 条」。
   `loadMore` 保留已有 `total`，不重新计数；切过滤、重试、清空筛选重新取第一页
   总数。旧后端没有 `total` 时退回「已加载 N 条」。
8. 不做页码/跳页、不返回「剩余条数」；导出继续用 `X-Export-Count`，不因本 ADR
   改变导出上限或格式。

## 4. 后果

- 首屏多一次 COUNT；加载更多保持原来的单查询。
- 管理员能看到当前过滤条件下的总量，但仍不能跳页；审计量很大时仍要依赖过滤或导出。
- `total` 与列表可能短暂不一致；并发恢复/保留清理时以刷新后的结果为准。
- 旧前端忽略额外字段；新前端遇到旧后端没有 `total` 时隐藏「共 N 条」。
- 普通管理员看到的是全量；没有额外的租户/部门维度（与现有审计权限一致）。

## 5. 验证

- 默认 **497 passed + 40 skipped**；真实 Postgres **534 passed + 3 skipped**；
  Postgres + Redis **537 passed**。
- `ruff check` / `ruff format --check`（194 files）/ `mypy app`（113 files）通过。
- 前端 `tsc`、**84 tests / 17 files**、`oxlint` 0/0（72 files）、
  `oxfmt --check` 80 files、`pnpm build` 通过。
- 覆盖：内存计数（用户、会话、组合、空结果）；API 第一页 `total`、第二页/空页
  `null`；按用户/会话/组合过滤的 total；计数失败 503。
- 无迁移；`session_restore_audits` 的写入/保留路径未改。

## 6. 待定

- 大数据量下的计数缓存/近似值；
- 页码/跳页；
- 审计统计聚合（按用户/会话/时间段的汇总，与列表 total 不同形状）；
- 下载审计与异步导出（ADR-0062 待定）；
- `total` 与列表的短期快照（当前接受两次查询的轻微不一致）。
