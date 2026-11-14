# ADR-0057：审批列表首屏总数

- 状态：已采纳
- 日期：2026-11-14
- 相关：[ADR-0052](0052-approval-list-pagination.md)（游标分页）、
  [ADR-0053](0053-resolved-approval-order.md)（已办排序）、
  [ADR-0054](0054-approval-list-filters.md)（已办筛选）

## 1. 背景

审批列表用 keyset 游标翻页，接口只返回当前页和 `next_cursor`，前端只能显示
「加载更多」。审批人看到第一页 50 条，不知道当前状态下总共有多少单、还剩多少；
统计接口给的是积压/窗口汇总，不能回答「这个筛选下有多少条」。

导出（ADR-0056）能拿到一次性快照，但导出是另一个动作，不能替代页面上的计数。
用户需要的是：进入列表就知道「共 N 条」，加载更多时知道「已显示 M 条」。

## 2. 备选方案

| 方案 | 取舍 |
|---|---|
| 每页都返回 `total` | 每次「加载更多」都多一次 `COUNT`，而总数在翻页期间不会变；否决 |
| 单独加 `GET /approvals/count` | 页面要发两个请求、维护两套 loading/error，首次渲染还要等计数；否决 |
| 列表 SQL 用 `COUNT(*) OVER()` 一次查询 | 少一次查询，但计数是窗口函数在游标过滤之后算的，翻页时不是全局总数；要给待办/已办两套查询加列，改动面大；否决 |
| 第一页附带 `total`，后续页为 `null` | 一次列表请求拿到首屏总数，加载更多不重复计数；采纳 |

## 3. 决策

1. `ApprovalListResponse` 增加 `total: int | None`。只在请求**没有 `cursor`** 时返回；
   后续页固定为 `null`。前端把 `null` 当「未知」，不显示「共 N 条」，兼容旧后端。
2. 计数与列表使用同一口径：同一个 `status`、同一组已办筛选、同一身份范围
   （审批人看全部，普通员工只看自己发起的）。待办列表仍不接受筛选。
3. 存储层新增 `ApprovalStore.count(status, requested_by, filters) -> int`：
   - 内存实现遍历记录，复用 `ApprovalListFilters.matches()` 的筛选语义；
   - Postgres 用 `SELECT count(id)`，已办仍要求 `resolved_at IS NOT NULL`，
     筛选条件与列表共用 `_resolved_filter_conditions()`，避免口径分叉。
4. 服务层新增 `count_for(identity, status, filters, expire=True)`。列表接口在
   `list_for()` 之后调用 `count_for(expire=False)`：`list_for` 已经收敛过超时待办，
   同一请求不再重复扫描。
5. 计数与列表是两次查询，不是同一快照：两次查询之间新增/决议的审批会让 `total`
   与当前页略有出入；前端以列表为准，`total` 只是导航信息。刷新后重新对齐。
6. 无迁移、无新索引。`COUNT` 可能扫描已办索引后的残余行；工具/审批人没有独立
   索引，大数据量下计数会比列表慢，明确接受首屏成本。超过阈值再评估缓存或
   近似计数。
7. 前端在列表顶部显示「共 N 条」；当 `items.length < total` 时显示「共 N 条，
   已显示 M 条」。切状态、应用/清除筛选、决议后刷新都会重新取第一页总数；
   `loadMore` 保留已有 `total`，不重新计数。
8. 不做页码/跳页、不返回「剩余条数」、不改导出；导出已有 `X-Export-Count`。

## 4. 后果

- 首屏多一次 `COUNT`，但只在第一页；加载更多保持原来的单查询。
- `total` 与列表可能短暂不一致；并发决议时以刷新后的结果为准。
- keyset 分页的语义不变：仍然没有页码，不能跳到第 N 页。
- 普通员工看到的总数只覆盖自己发起的审批；筛选不会绕过 `requested_by`。
- 旧前端忽略额外字段；新前端遇到旧后端没有 `total` 时隐藏计数。

## 5. 验证

- 默认 **487 passed + 40 skipped**；真实 Postgres **524 passed + 3 skipped**；
  Postgres + Redis **527 passed**。
- `ruff check` / `ruff format --check`（188 files）/ `mypy app`（110 files）通过。
- 前端 `tsc`、**80 tests / 16 files**、`oxlint` 0/0（68 files）、
  `oxfmt --check` 76 files、`pnpm build` 通过。
- 覆盖：内存筛选计数；API 第一页 `total`、后续页 `null`；审批人/普通员工
  可见范围计数；Postgres 待办与已办筛选计数。
- 无迁移。

## 6. 待定

- 大数据量下的计数缓存/近似值；
- 页码/跳页；
- 按当前筛选导出统计聚合（与逐条导出不同形状）；
- `total` 与 `next_cursor` 是否做短期快照（当前接受两次查询的轻微不一致）。
