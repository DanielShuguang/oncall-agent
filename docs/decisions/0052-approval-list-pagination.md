# ADR-0052 审批列表游标分页

## 1. 背景

`GET /api/approvals` 从 W3 起只支持 `status` + `limit`（1–200，默认 50），
没有游标。审批中心能筛待办/已办，但只能看到第一页；当待办积压超过 200 条时，
更早的审批在 UI 上根本到不了，审批人只能靠调大 `limit` 或直接查库。

ADR-0048 给审批统计加了积压/等待指标，但列表本身仍是「一页定死」；
ADR-0051 的分组统计也不能替代逐条处理。审批列表需要一个可翻页的接口，
且不能引入新的表或索引迁移。

```sql
-- 现有索引，只能帮到 pending 的第一页
CREATE INDEX idx_approvals_pending ON approvals (status, expires_at);
```

## 2. 备选方案

| 方案 | 为什么没选 |
|---|---|
| `offset` / 页码 | 决议会把记录从 pending 移走，后续页会跳过或重复；审批场景不能接受 |
| 前端过滤已加载列表 | 只能过滤已经拉到的 50 条，解决不了「看不到更早的」 |
| 只按 `created_at` 做游标 | 同微秒的审批需要额外 tiebreaker；列表主排序是 `expires_at` |
| 一次性拉全量/把上限提到几千 | 无界响应；审批多了会拖垮页面与数据库 |
| **`(expires_at, created_at, id)` keyset** | 与现有排序一致、翻页稳定、无需迁移 |

## 3. 决策

1. 列表按 `(expires_at, created_at, approval_id)` 升序；`approval_id` 只做
   同时间戳的 tiebreaker。内存与 Postgres 用同一个全序。
2. 游标是 base64url 的 JSON `{"e": expires_at, "c": created_at, "i": id}`，
   最长 512 字符；解析失败/字段非法返回 `400 {"code":"INVALID_CURSOR"}`，
   不静默从头开始。
3. `next_cursor` 只在当前页取满时返回；下一页为空时返回 `items: []` 且
   `next_cursor: null`。`limit` 仍为 1–200、默认 50。
4. 游标只配合同一个 `status` 使用：列表按 `status` 过滤，跨状态复用游标
   会从错误的元组位置开始，结果不可解释。UI 切状态/刷新时重置游标。
5. 无迁移、无新索引。`(status, expires_at)` 已能支撑待办第一页；已办状态
   在数据量变大后可能扫描更多行，属可接受代价，后续再评估 `resolved_at` 索引。
6. 前端「加载更多」追加当前页并更新游标；状态切换、决议后刷新、卸载都会
   递增请求 token，旧页不会追加到新状态列表。
7. 不改变「已办按 `expires_at` 排序」的既有口径，不做 `resolved_at` 过滤、
   总数、跳页或导出；这些留给后续 ADR。

## 4. 后果

- 翻页期间如果有审批被决议，pending 列表的后续页可能重复或跳过；刷新即
  回到第一页。这与 keyset 的通用语义一致，文档里写清。
- 游标不签名：伪造只能改变自己的起点，服务端仍按 `identity` 过滤可见范围，
  不会越权读到别人的审批。
- 没有总数，审批中心无法显示「共 N 条」；v1 只保证能持续往下翻。
- 列表 SQL 多了一个 `OR` 条件；待办走现有索引，已办在大数据量下是已知
  的性能待定项。

## 5. 验证

- 默认 `pytest` **481 passed + 38 skipped**；真实 Postgres **516 passed + 3
  skipped**；Postgres + Redis **519 passed**。
- `ruff check` 通过、`ruff format --check` 187 files、`mypy app` 110 files。
- 前端 `tsc`、**74 tests / 15 files**、`oxlint` 0/0（66 files、231 rules）、
  `oxfmt --check` 74 files、`pnpm build` 通过。
- 覆盖：内存/Postgres keyset 翻页（含同时间戳按 id 兜底）、API 游标往返、
  非法游标 400、空页。无迁移。

## 6. 待定

- 已办列表改按 `resolved_at` 排序/筛选，以及对应的索引；
- 总数、跳页、导出；
- 游标签名/过期；
- 已办状态大数据量下的查询计划与索引；
- 前端是否记住每个状态的游标（v1 切状态即重置）。
