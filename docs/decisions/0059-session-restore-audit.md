# ADR-0059：已移除会话的恢复审计

- 状态：已采纳
- 日期：2026-11-14
- 相关：[ADR-0041](0041-session-remove.md)（会话从列表移除）、
  [ADR-0043](0043-hidden-session-restore.md)（单条恢复）、
  [ADR-0049](0049-hidden-session-batch-restore.md)（批量恢复）、
  [ADR-0055](0055-hidden-restore-results.md)（逐条结果）

## 1. 背景

批量恢复已经返回「本次真正恢复了哪些会话」的逐条结果，但这是**响应级**信息：
请求结束后没有留下「谁在何时恢复了哪些会话」的凭据。`hidden_sessions` 的行在
恢复时被删除，run、事件、审批与引用快照都不记录这次恢复动作；结构化日志可以
看到一次请求，但不能按用户查、不能作为管理页的数据源，也不能独立于应用日志
保留。

企业服务台把「把会话从已移除列表恢复」视为一次治理动作：管理员需要能回答
「u_102 上周恢复了哪些会话」「这次批量恢复请求了几个、实际恢复了几个」。这不是
会话内容审计（正文仍按 ADR-0021/0023 保留），而是操作审计。

## 2. 备选方案

| 方案 | 为什么没选 |
|---|---|
| 只写结构化日志 | 不可按用户/时间查询，不能作为管理接口数据源；日志轮转后丢失 |
| 每个恢复的 session 一行 | 同一次批量恢复的 `user_id`/`restored_at`/请求数重复存；批量语义被拆散 |
| 在 `hidden_sessions` 加 `restored_at` 字段 | 恢复时行被删除，字段随之消失；无法保留历史 |
| 复用 `run_events` 记一条审计事件 | 事件属于 run，恢复动作没有 run；且事件保留期与审计保留期不同 |
| 独立审计服务/消息队列 | 私有化部署多一个组件；当前量级用一张表足够 |
| **按一次恢复操作落一行，独立保留期** | 批量语义完整、可查询、实现小；采纳 |

## 3. 决策

1. 新增 `session_restore_audits` 表，按**一次恢复操作**一行：`id`（批次 UUID）、
   `user_id`、`session_ids`（真正恢复的 id，按去重后的请求顺序）、
   `requested_count`（去重后的请求数）、`restored_count`、`restored_at`。
   只记录真正恢复的 id；不存在的、属于别人的、本来没移除的 id 不写入。
2. `restored_count = jsonb_array_length(session_ids)` 用 CHECK 约束兜底，避免冗余
   计数与数组漂移。`requested_count - restored_count` 表示本次未恢复的 id 数。
3. 审计写入与删除 `hidden_sessions` 在**同一事务**内完成：Memory 实现在同一把锁
   内删行并追加记录；Postgres 在 `session.begin()` 里 `DELETE ... RETURNING` 后
   `INSERT`。插入失败会回滚删除，不能出现「恢复成功但审计丢失」。
4. 没有真正恢复任何会话时不写审计：空请求、全是不存在/别人的 id、重复恢复都
   不产生行。审计记录的是「发生过的恢复」，不是「尝试过的恢复」。
5. 新增只读管理接口 `GET /admin/session-restores`，要求 `ONCALL_ADMIN_ROLES`；
   `user_id` 可选过滤，`limit` 1–200 默认 50，按 `restored_at DESC, id DESC`
   返回。不做分页、导出与前端管理页：审计表按 365 天保留，管理页先看最近记录。
6. 保留期独立配置 `ONCALL_SESSION_RESTORE_AUDIT_RETENTION_DAYS`（默认 365 天），
   接入现有 `RetentionSweeper`、`prune` CLI 与后台日志；不复用事件/正文保留期。
   审计是治理凭据，不应随会话正文一起被清掉。
7. 审计表无外键：会话由 `runs.session_id` 投影，run/事件可能先被保留策略清掉；
   审计要独立留存。`user_id` 只存字符串，不依赖用户目录（当前也没有）。

## 4. 后果

- 管理员可以按用户查最近的恢复批次，看到请求数、实际恢复数与恢复的 session id。
- 每次恢复多一次插入；恢复本身是低频人工动作，写放大可接受。
- 一条审计对应一次批量操作，不能直接按单个 session 反查（`session_ids` 是 JSONB
  数组，当前没有 GIN 索引）；需要逐 session 查询时再加索引/端点。
- 审计不是防篡改账本：拥有数据库写权限的人仍可修改/删除；当前只保证应用层
  原子写入与独立保留。
- 未恢复的 id 不落库，因此无法从审计回答「用户尝试恢复但失败了哪些」；逐条
  结果仍在响应里，且刻意不区分「不存在」与「属于别人」。
- 旧客户端不受影响：恢复端点响应不变，审计是服务端副作用；前端没有新增页面。
- 管理接口不可用时返回 503，不返回空列表冒充「没有恢复记录」。

## 5. 验证

- 默认 **492 passed + 40 skipped**；真实 Postgres **529 passed + 3 skipped**；
  Postgres + Redis **532 passed**。
- `ruff check` / `ruff format --check`（192 files）/ `mypy app`（112 files）通过；
  前端未改，沿用 **81 tests / 16 files**、`oxlint` 0/0、`oxfmt --check` 76 files、
  `pnpm build`。
- 迁移 `0019`：`upgrade head` → `alembic check`（No new upgrade operations
  detected）→ `downgrade 0018` → `upgrade head` 往返通过。
- 覆盖：内存/Postgres 契约（单条与批量恢复各写一条、按用户过滤、最新在前、
  重复/空恢复不写）；恢复审计按 366 天阈值 dry-run 预览后实删、第二轮为 0；
  admin 接口 403 / 列表 / `user_id` 过滤 / `limit` 校验 / 503；配置 0 天启动拒绝；
  迁移建表、CHECK、两条索引与 downgrade。

## 6. 待定

- 审计列表分页与 CSV 导出（当前只给最近 50 条）；
- 前端管理页与按 session 反查（需要 JSONB GIN 索引或明细表）；
- 防篡改（链式哈希/外部归档）与审计访问日志；
- 记录失败的恢复尝试（需要区分「不存在」「属于别人」「未移除」而不再泄露存在性）；
- 管理员跨用户恢复/清理（ADR-0049 待定，权限与隐私设计更大）。
