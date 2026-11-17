# ADR-0089：置顶审计统计跟随列表过滤与日期范围

- 状态：已接受（W6 后补）
- 日期：2026-11-17
- 相关：[ADR-0081](0081-session-pin-audit.md)、[ADR-0085](0085-session-pin-audit-console.md)、[ADR-0086](0086-session-pin-audit-date-range.md)、[ADR-0087](0087-session-pin-audit-stats.md)
- 迁移：无（仍 `0022`）

## 背景

置顶审计已有列表、用户/会话/动作/日期过滤和 keyset 分页（ADR-0081/0082/0086），
管理页也有全局 7/30/90 天统计卡（ADR-0085/0087）。但统计接口只接受 `days`，固定
全局口径；管理员在页面上按某个用户、某个会话、某类动作或某段日期筛选后，列表已经
收窄，顶部统计卡却仍显示全局数字。

两个口径并排会让页面上出现「列表只有 1 条，统计卡说 20 次置顶」的误读。恢复审计
统计（ADR-0066/0067）已经证明「统计跟随同一过滤条件」是更符合管理页直觉的口径。

## 备选方案

| 方案 | 结论 |
|---|---|
| 前端遍历当前已加载页求和 | 只覆盖已加载页；换过滤/翻页即失真，且「涉及用户数」无法从当前页还原 |
| 统计只保留全局，页面另加「过滤后统计」小字 | 两个数字并排，解释成本高，仍会误读 |
| 新增独立 `/stats/filtered` 端点 | 与列表过滤参数重复，多一套校验/文档/客户端；没有独立语义 |
| 统计只接受日期范围，不接受用户/会话/动作 | 页面筛选用户/动作后统计仍不一致，只解决一半问题 |
| **统计复用列表的过滤参数，`days` 与日期范围二选一** | 与恢复审计统计一致；页面一个口径；后端只多一个 `where` 条件 |

采纳：扩展 `GET /admin/session-pins/stats`，接受与列表相同的 `user_id`/`session_id`/
`action`/`created_from`/`created_to`；`days` 可选，与日期范围二选一。

## 决策

1. **过滤参数与列表同义**：`user_id`/`session_id` 1–64、`action` 只接受 `pin`/`unpin`；
   未知参数仍由 FastAPI 拒绝或忽略的既有行为不变。过滤只影响 `pins`/`unpins`/
   `users`/`sessions`/`daily`，不改变列语义。
2. **`days` 与日期范围二选一**：`days` 可选 1–365，缺省 30；`created_from`/`created_to`
   必须同时提供、`from <= to`、最多 365 天；两者同时出现返回 `422 INVALID_RANGE`，
   只给一端也返回 `422 INVALID_RANGE`。日期范围内部窗口为
   `[from 00:00Z, to 次日 00:00Z)`，`until` 回显为 `to 次日 00:00Z - 1µs`，`days`
   回显闭区间天数。这样统计和列表的日期边界完全一致，且响应中的 `until` 是包含的。
3. **过滤后仍是同一窗口**：`pins`/`unpins` 只统计命中过滤的记录；`users`/`sessions`
   是命中记录内去重后的操作者/会话数；`daily` 只含命中记录的 UTC 有活动日，
   稀疏、不补零，`pins`/`unpins` 之和分别等于汇总。没有命中时全 0、`daily=[]`，
   不是 404。
4. **存储层只加过滤条件**：`session_pin_audit_stats` 增加可选 `user_id`/`session_id`/
   `action`；内存遍历时先过滤；Postgres 在汇总与日趋势共用的 `window` 子查询上追加
   `where`，避免两套过滤条件漂移。继续复用 `idx_session_pin_audits_time`，无迁移。
5. **前端统计卡跟随已应用过滤**：`getSessionPinAuditStats(days, filters)` 先拼过滤，
   日期范围存在时省略 `days`；统计 effect 依赖 `[filters, statsDays]`，切换过滤/窗口
   时清空旧统计并带请求 token，避免旧响应覆盖。统计卡文案区分「全部用户/已应用筛选」，
   日期范围生效时隐藏 7/30/90 按钮并显示「按筛选日期（N 天）」。
6. **卡片独立文件**：`PinAuditStatsCard.tsx` 从 `PinAuditSections.tsx` 拆出，保持
   `PinAuditSections` 在 300 行限制内；不改列表/导出路径。
7. **失败语义不变**：统计查询 `SQLAlchemyError` → 503 `DATABASE_UNAVAILABLE`；
   统计失败只显示统计错误卡，不影响列表/导出。

## 后果

- 管理页列表与统计卡使用同一过滤条件，按用户/会话/动作/日期筛选后数字自洽。
- 统计与列表仍是两次独立查询，不承诺严格同一快照；并发写入可能相差一条，页面接受。
- `daily` 是过滤后的稀疏日；没有活动时为空数组，前端不能把空数组当错误。
- 日期范围与 `days` 二选一降低了「两个窗口叠加」的歧义，但调用方不能同时传；
  旧调用 `?days=30` 行为不变。
- 统计卡跟随过滤后，全局视图需要清空筛选才能看到；这是管理页的预期交互，文档已写明。
- 过滤字段都走现有索引前缀（`created_at`），当前数据量不需要额外索引或缓存。

## 验证

- 后端 `test_admin_pins.py`：`user_id=u_102` → 1 pin/1 unpin、users/sessions 1/1；
  `action=pin` → 2/0；当日日期范围 → `days=1`、1/1；`days` + 日期范围 422；
  单端日期 422；`days=0/366` 422。
- `test_store_contract.py`：按 `user_id` 与 `user_id+action=pin` 过滤的 stats 与
  审计记录逐项对齐（3 pins/2 unpins、users=1、sessions=2、daily 求和）。
- 前端 `pinAudits.test.ts`：过滤参数仍带 `days=30`；日期范围只发 `created_from/to`。
- 实测：默认 **516 passed + 40 skipped**；Postgres-only **553 passed + 3 skipped**；
  Postgres + Redis **556 passed**；`ruff check` / `ruff format --check` 200 files /
  `mypy app` 116 files；前端 **26 files / 125 tests**、tsc、oxlint 0/0、oxfmt、
  `pnpm build` 通过。
- 迁移 `0022` 往返通过（`upgrade head` → `alembic check` → `downgrade 0021` →
  `upgrade head`），无新迁移。

## 待定

- 统计卡支持按小时分布/图表库；缓存或物化；导出统计 CSV 另见 ADR-0070 的恢复审计，
  置顶审计暂不做。
- 多副本下的统计缓存与时间窗口边界。

