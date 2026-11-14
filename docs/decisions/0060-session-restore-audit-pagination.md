# ADR-0060：会话恢复审计列表游标分页

- 状态：已采纳
- 日期：2026-11-14
- 相关：[ADR-0059](0059-session-restore-audit.md)（会话恢复审计）、
  [ADR-0052](0052-approval-list-pagination.md)（审批列表游标分页）、
  [ADR-0021](0021-data-retention.md)（保留清理）

## 1. 背景

ADR-0059 的 `GET /admin/session-restores` 只支持 `user_id` 与 `limit`，默认返回
最近 50 条。审计表按 365 天保留，一个活跃管理员/租户很容易超过这个数量；超过
50 条后，更早的恢复批次在管理接口不可达，只能改 `limit` 到 200 或直接查库。
`limit=200` 仍然有界，且把「当前页」和「一共有多少」混在一起。

审批列表已经用 keyset 游标解决了同类问题（ADR-0052），恢复审计也按
`(restored_at, id)` 倒序，适合复用同一模式：第一页之后用「上一页最后一条」作为
游标，不依赖 offset。

## 2. 备选方案

| 方案 | 为什么没选 |
|---|---|
| 只把 `limit` 提高到 200/1000 | 仍然有界；大 `limit` 一次拉全表，管理端更慢 |
| `OFFSET` 分页 | 审计只追加、清理只删旧行；翻页期间新记录插入会导致重复/跳过，offset 越深越慢 |
| 页码 + 总数 | 需要额外 COUNT；管理接口不是高频页面，当前不值得 |
| 前端一次拿全量再本地分页 | 审计表可到 365 天，响应不可控 |
| 按 `restored_at` 单键游标 | 同一毫秒可能有多条；没有确定性 tiebreaker 会漏/重 |
| **`(restored_at, id)` 倒序 keyset** | 与现有排序一致、无迁移、实现小；采纳 |

## 3. 决策

1. `GET /admin/session-restores` 增加可选 `cursor`（最长 512 字符）。服务端按
   `(restored_at, id)` 倒序，游标表示「严格早于这个元组」；下一页从它之后继续。
2. 游标是 base64url 编码的 JSON `{"t": ISO8601, "i": audit UUID, "u": user_id}`：
   - `t` 必须是带时区的 ISO 8601；`i` 必须是 UUID；
   - `u` 是本次请求的 `user_id` 过滤（未过滤时为 `null`），解码时与 query 比较，
     不一致返回 400。否则「先用全量游标、再切到按用户过滤」会从错误位置开始，
     且看起来像正常响应。
3. `next_cursor` 只在**取满 `limit`** 时返回；下一页为空时返回
   `{"items": [], "next_cursor": null}`。这与审批列表一致，调用方不需要根据
   `items` 数量猜测是否还有下一页。
4. 非法/过期/混用过滤条件的游标统一返回
   `400 {"code":"INVALID_CURSOR"}`；不降级为空列表，避免把「游标坏了」误判成
   「没有更多审计」。
5. 不新增迁移/索引：现有 `idx_session_restore_audits_user_time` 与
   `idx_session_restore_audits_time` 支持按 `user_id`/时间缩小范围；`id` 只做
   同一时间戳的 tiebreaker，审计表是低频治理数据，当前量级无需覆盖索引。
6. 不做 CSV 导出、总数、跳页与前端管理页；接口仍是管理员只读，`limit` 仍为
   1–200 默认 50（CSV 导出后续由 ADR-0062 补上；前端管理页由 ADR-0063 补上）。

## 4. 后果

- 管理员可以稳定翻完 365 天内的审计记录；每页多一次轻量查询，没有 COUNT。
- 翻页期间发生新的恢复操作时，新记录只会出现在第一页，旧游标继续沿旧位置
  向后；不会因为插入而重复整页，但也不会看到翻页开始后才产生的记录（与
  ADR-0052 的 keyset 语义一致）。
- 游标绑定 `user_id`：切换过滤条件必须从第一页重新拉取；这是有意的，避免把
  两种过滤结果拼在一起。
- 游标不是签名令牌：客户端可以伪造 `t`/`i` 跳到任意时间/记录，但只能读取
  自己本就有权读取的管理数据；防篡改不在本 ADR 范围。
- 没有总数：管理端只能看到「还有下一页」，不能显示「共 N 条」；需要时再加
  `total` 或近似计数。
- 没有返回 `next_cursor` 表示本页没取满，已经是最后一页；调用方应以
  `next_cursor == null` 作为结束条件。

## 5. 验证

- 默认 **493 passed + 40 skipped**；真实 Postgres **530 passed + 3 skipped**；
  Postgres + Redis **533 passed**。
- `ruff check` / `ruff format --check`（192 files）/ `mypy app`（112 files）通过；
  前端未改，沿用 **81 tests / 16 files**、`oxlint` 0/0、`oxfmt --check` 76 files、
  `pnpm build`。
- API：3 条用户审计 + 1 条其他用户审计，`limit=2` 翻三页（2/2/0），`next_cursor`
  在空页为 `null`，三页 id 不重复；非法游标 400；全量游标复用到
  `user_id` 过滤 400。
- 存储契约（内存 + Postgres）：3 条审计按 `(restored_at, id)` 倒序，limit=2 后
  用最后一条的 `(restored_at, audit_id)` 取下一页，恰好 1 条且与第一页不重叠。
- 同一 `restored_at` 的两条审计按 `id` 倒序；把游标里的 UUID 改成大写后仍从
  同一位置继续（解码时统一归一化）。
- 无迁移、无前端改动；审批/会话的其他分页行为未变。

## 6. 待定

- 审计列表 CSV 导出（已由 ADR-0062 补上）与总数（仍未做）；
- 按单个 session 反查（需要 JSONB GIN 索引或明细表，ADR-0059 待定；
  已由 [ADR-0061](0061-session-restore-audit-session-filter.md) 实现）；
- 游标签名/过期（防伪造跳记录，当前内网管理接口可接受）；
- 前端管理页（当前只有 admin API）。
