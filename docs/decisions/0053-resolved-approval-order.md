# ADR-0053 已办审批按决议时间排序

## 1. 背景

ADR-0052 给审批列表加了 keyset 游标，但排序键仍然是 `(expires_at, created_at,
approval_id)` 升序——这是为待办设计的：审批人要从最急的（最快过期）开始处理。
已办列表沿用了同一顺序，于是最近处理的审批可能排在很后面，审批人想回看「刚刚批了
什么」要一直往下翻。

`approvals` 表已有 `resolved_at`（通过/拒绝/过期时写入），统计接口也一直用它算
等待时长；已办列表却没有按它排序。ADR-0052 的「待定」第一条就是这件事。

```sql
-- ADR-0052 之后：待办与已办共用同一个排序/索引
CREATE INDEX idx_approvals_pending ON approvals (status, expires_at);
```

## 2. 备选方案

| 方案 | 为什么没选 |
|---|---|
| 前端对当前页再排序 | 只能改一页的顺序，跨页仍然是错的；翻页会跳记录 |
| 加 `sort=resolved_at` 让客户端选 | 排序与游标形状必须匹配，多一个参数就多一组非法组合；已办没有理由按到期时间排 |
| 全部状态统一按 `resolved_at` 倒序 | 待办没有 `resolved_at`，且审批人需要按到期紧迫度处理待办 |
| 已办改用 `offset` 分页 | 新决议会插到最前，后续页重复/跳过；与 ADR-0052 的结论冲突 |
| **按 `status` 分流：待办按到期升序，已办按决议倒序** | 两种列表各有明确语义，游标形状随状态变化，客户端无需理解排序细节 |

## 3. 决策

1. `status=pending`（以及内部 `status=None`）保持 `(expires_at, created_at,
   approval_id)` 升序，最急的在前；这是 ADR-0052 的既有行为，不改。
2. `status=approved|rejected|expired` 按 `(resolved_at, approval_id)` 倒序，
   最近的决议在前。`expired` 的 `resolved_at` 是 `expire_due` 收敛的时刻，
   因此四类状态都能落在这个全序里；`resolved_at IS NULL` 的脏数据不进入已办列表。
3. 游标形状跟着状态走：待办是 base64url JSON `{"e","c","i"}`（ADR-0052），
   已办是 `{"s","r","i"}`（`s` 是 `approved|rejected|expired`）。解析时先看
   `status` 再选解码器，并校验 `s` 与请求状态一致；把待办游标用到已办、
   把已办游标用到待办，或在三种已办状态之间混用，都返回
   `400 {"code":"INVALID_CURSOR"}`，不静默从头开始。
   ADR-0052 生成的已办游标（`{e,c,i}`）在新版本失效；本 ADR 最初版本的
   `{r,i}` 游标也因新增 `s` 失效，刷新即回第一页；待办游标继续有效。
4. 新增部分索引 `idx_approvals_resolved (status, resolved_at, id)
   WHERE resolved_at IS NOT NULL`（迁移 0018）。查询里本来就有
   `resolved_at IS NOT NULL`，可命中该索引；索引用默认升序，PostgreSQL 反向
   扫描即可满足两列同时 DESC 的排序与 keyset 条件。
5. 前端已办列表的表头从「过期时间」改为「决议时间」，显示 `resolved_at`；
   待办仍显示 `expires_at`。只改展示，不改决议/过期逻辑。
6. 不做按工具/审批人/时间筛选，不做总数、跳页、导出；这些仍是后续 ADR 的范围。
   列表仍复用 ADR-0052 的「取满才给 `next_cursor`」与请求 token 防竞态。

## 4. 后果

- 已办列表的顺序变了：升级后最近决议的记录出现在最前，旧的已办游标失效一次。
  这是有意的契约变化，写进 `docs/03`。
- 列表 SQL 按 `status` 走两个分支；待办仍用 `idx_approvals_pending`，已办走
  新索引。部分索引不包含 pending 行，写入成本与原表相同量级。
- `resolved_at` 为空的已办行会被隐藏；正常路径不会出现（`resolve` 与
  `expire_due` 都写该字段），出现即视为脏数据。
- 翻页期间新决议会插到已办列表最前，后续页可能重复/跳过；刷新即回第一页，
  与 keyset 的通用语义一致。
- 索引迁移只加索引、不回填数据，可在业务低峰执行；`downgrade` 直接删索引。

## 5. 验证

- 默认 `pytest` **483 passed + 39 skipped**；真实 Postgres **519 passed + 3
  skipped**；Postgres + Redis **522 passed**。
- `ruff check` 通过、`ruff format --check` 188 files、`mypy app` 110 files。
- 前端 `tsc`、**74 tests / 15 files**、`oxlint` 0/0、`oxfmt --check` 74 files、
  `pnpm build` 通过。
- 覆盖：内存/Postgres 已办倒序与同时间戳按 id 兜底、API 已办游标往返、
  待办/已办以及已办不同状态之间的游标混用 400、空页；迁移 0018 `upgrade → check → downgrade
  → upgrade` 无漂移。

## 6. 待定

- 已办按工具/审批人/决议日期筛选；
- 已办总数、跳页、导出；
- `expired` 是否应单独展示「过期时间」而不是「决议时间」；
- 数据量很大时是否把 `expires_at` 并入已办索引做覆盖索引；
- 游标签名/过期（与 ADR-0052 同一待定项）。
