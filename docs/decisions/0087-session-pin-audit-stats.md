# ADR-0087：置顶审计按日统计

- 状态：已接受（W6 后补）
- 日期：2026-11-17
- 相关：[ADR-0081](0081-session-pin-audit.md)、[ADR-0085](0085-session-pin-audit-console.md)、[ADR-0086](0086-session-pin-audit-date-range.md)
- 迁移：无（仍 `0022`）

## 背景

置顶审计已经有列表、按用户/会话/动作/日期过滤、keyset 分页和 CSV 导出（ADR-0081/0082/0084/0086），

管理页也有只读列表（ADR-0085）。但页面只能逐页看记录，回答不了交接/容量评估最常问的

两个问题：

- 最近 7/30/90 天置顶和取消置顶各发生多少次？
- 涉及多少用户、多少个会话，活动集中在哪些日期？

在浏览器里拼列表求和既慢又容易只覆盖已加载页；给列表加聚合过滤也不是同一个口径。

## 备选方案

| 方案 | 结论 |
|---|---|
| 前端遍历已加载页求和 | 只覆盖当前页/已加载页，换过滤或翻页就失真 |
| 列表接口增加 `total`/分组 | 列表是细目，不应同时承担窗口聚合；会打乱分页口径 |
| 新表/物化视图预聚合 | 数据量很小（审计行按操作产生），多一张表和多一条写链路不值得 |
| 复用恢复审计的统计接口 | 表、字段与语义都不同，硬复用会污染契约 |
| 统计跟随列表过滤 | 统计卡会随下方筛选变化，无法回答全局「最近 N 天」；且需要再定义过滤后的统计口径 |

采纳：在 `GET /admin/session-pins` 旁新增 `GET /admin/session-pins/stats`，全局窗口汇总 +

UTC 稀疏日趋势，不接列表过滤。

## 决策

1. **独立端点**：`GET /admin/session-pins/stats?days=30`，管理员只读；`days` 1–365，
   默认 30；窗口为 `[until - days 天, until]`，`until = now(UTC)`。
2. **全局口径**：不接受 `user_id`/`session_id`/`action`/日期范围；需要过滤后的细目
   用列表或导出。页面统计卡不随下方筛选变化，避免两个口径混用。
3. **汇总字段**：`pins`/`unpins` 是窗口内显式状态变化次数（与审计行一一对应）；
   `users`/`sessions` 是窗口内去重后的操作者与会话数；`since`/`until` 回显窗口。
4. **稀疏日趋势**：`daily` 只返回有审计活动的 UTC 日期，每行 `{day, pins, unpins}`，
   升序、不补零；`pins`/`unpins` 之和分别等于汇总。低频数据下 30 个空日不值得画。
5. **存储实现**：内存遍历审计记录按 UTC 日期聚合；Postgres 用
   `count(distinct user_id)`/`count(distinct session_id)` 求汇总，再按
   `date(timezone('UTC', created_at))` + `action` 分组求日趋势；`pins`/`unpins`
   从 daily 行求和，保证「日趋势之和等于汇总」不被并发写入破坏。复用
   `idx_session_pin_audits_time`，无迁移。
6. **失败语义**：统计与列表同走 `SQLAlchemyError` → 503 `DATABASE_UNAVAILABLE`；
   统计失败不影响列表加载（前端独立错误卡）。
7. **前端范围**：管理页顶部 7/30/90 天切换，四项汇总 + 最近 7 个有活动日期的
   「MM-DD · 置顶 N / 取消 M」；不做图表库、缓存、按过滤统计或导出统计。

## 后果

- 管理页能直接回答全局窗口问题，交接时不需要手工翻页或下载 CSV 再算。
- 统计与列表是两次查询，可能相差一条刚写入的审计；页面不承诺同一快照。
- `daily` 稀疏，前端需要接受空数组并只展示已有日期；不能把空数组当成错误。
- 统计是全局口径，管理员想按用户/会话看细目仍需列表或导出。
- `pins`/`unpins` 从 `daily` 行求和，二者始终一致；`users`/`sessions` 是同一窗口
  的另一条 distinct 聚合，并发写入时可能与 `daily` 相差一条，页面不承诺严格同一快照。
- 数据量随操作增长，聚合走 `created_at` 索引；当前量级不需要缓存或物化。

## 验证

- 后端 `test_admin_pins.py` 新增 stats 用例：2 pin + 1 unpin → `pins=2`/`unpins=1`/
  `users=2`/`sessions=2`/`daily` 1 天；403/503 覆盖 stats；`days=0/366` 422。
- `test_store_contract.py` 的 `_exercise_pinned_sessions` 将 stats 与全量审计逐项对齐
  （pins/unpins/users/sessions、daily 求和），并校验 2000 年空窗口全 0。
- 前端 `pinAudits.test.ts` 断言 stats 请求/解析；管理页统计卡与列表独立加载。
- 实测：默认 **516 passed + 40 skipped**；Postgres-only **553 passed + 3 skipped**；
  Postgres + Redis **556 passed**；`ruff check` / `ruff format --check` 200 files /
  `mypy app` 116 files；前端 **119 tests / 25 files**、tsc、oxlint 0/0（88 files）、
  oxfmt 96 files、`pnpm build` 2900 modules/588ms。
- 迁移 `0022` 往返通过（`upgrade head` → `alembic check` → `downgrade 0021` →
  `upgrade head`），无新迁移。

## 待定

- 统计卡跟随列表过滤（需要另定义过滤后的汇总口径）。
- 按小时分布、图表库、缓存/物化、CSV 导出统计。
- 多副本下的查询缓存与时间窗口边界。
