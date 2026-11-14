# ADR-0061：会话恢复审计按 session 反查

- 状态：已采纳
- 日期：2026-11-14
- 相关：[ADR-0059](0059-session-restore-audit.md)（会话恢复审计）、
  [ADR-0060](0060-session-restore-audit-pagination.md)（审计列表分页）、
  [ADR-0021](0021-data-retention.md)（保留清理）

## 1. 背景

ADR-0059 把每次恢复操作写成一行 `session_restore_audits`，`session_ids` 是
JSONB 数组，只存真正恢复的 id。管理接口可以按 `user_id` 看「某人恢复过什么」，
但不能回答反向问题：「这个会话被谁、在什么时候恢复过？」

审计要用于事件复盘：用户报「会话被误删后又出现」，管理员需要从 `session_id`
查回恢复批次、操作者和时间。当前只能拉全量审计再在客户端过滤，365 天保留期
下不可行。`session_ids` 是数组，普通 B-tree 索引无法加速「数组包含某个值」。

## 2. 备选方案

| 方案 | 为什么没选 |
|---|---|
| 管理端拉全量后客户端过滤 | 365 天审计量不可控，响应和内存都浪费 |
| 只加 `session_id` 查询、不加索引 | 能查，但每次都是全表扫描；审计是低频管理查询，不值得留一个明显慢路径 |
| 建明细表 `(session_id, audit_id)` | 查询最快，但每次恢复要写 N 行，且重复存 `user_id/restored_at`；当前批量审计表更简单，GIN 已够用 |
| JSONB 默认 `jsonb_ops` GIN | 支持更多操作符，但索引更大；本查询只用 `@>`，`jsonb_path_ops` 更小更快 |
| **`session_ids @>` + `jsonb_path_ops` GIN** | 一条索引覆盖包含查询，不改变审计行结构；采纳 |

## 3. 决策

1. `GET /admin/session-restores` 增加可选 `session_id`（1–64 字符，与
   `runs.session_id`/`hidden_sessions.session_id` 的 `String(64)` 一致）。它和
   `user_id` 可同时使用，语义是「这个用户在恢复这个会话时的批次」。
2. PG 查询用 `session_ids @> '["<session_id>"]'`（SQLAlchemy
   `SessionRestoreAuditRow.session_ids.contains([session_id])`）；内存实现用
   `session_id in record.session_ids`，两边同一包含语义。
3. 迁移 `0020` 新增
   `idx_session_restore_audits_sessions`：
   `USING gin (session_ids jsonb_path_ops)`。只服务 `@>` 包含查询，不替代已有的
   `(user_id, restored_at DESC)` 与 `(restored_at)` 索引。
4. 游标在无过滤时保持 ADR-0060 的 `{t, i, u}`；带 `session_id` 过滤时增加
   `s`。这样滚动升级期间旧实例仍能解析新实例返回的无过滤游标；只有真正带
   session 过滤的游标才是新形状。切换 `session_id` 后复用旧游标返回 400
   `INVALID_CURSOR`，避免把两个过滤结果拼在一起。
5. 兼容 ADR-0060 的旧游标：没有 `s` 的游标只在不带 `session_id` 的请求里继续
   可用；一旦请求带 `session_id`，旧游标按过滤不匹配处理。旧游标因此不需要
   强制刷新，也不会悄悄跨过滤翻页。
6. 分页语义不变：仍按 `(restored_at, id)` 倒序，`next_cursor` 只在取满
   `limit` 时返回；非法/混用过滤条件的游标 400，不降级为空列表。
7. 不做前端管理页、CSV 导出、总数/跳页。当前只有管理员只读 API；
   `session_id` 过滤是事件复盘入口，不是面向普通用户的会话历史查询。

## 4. 后果

- 管理员可以从一个 `session_id` 查到全部恢复批次，定位操作者、时间和同批
  恢复的其他会话；查询走 GIN，不需要扫 365 天全表。
- GIN 索引会增加恢复写入的成本和磁盘占用；恢复是低频操作，审计是治理数据，
  这个代价可接受。索引只支持包含语义，不支持按数组元素排序/范围查询。
- `session_id` 来自客户端，格式上限与现有会话字段一致；没有外键，会话被保留
  清理后审计仍可反查（审计要独立留存）。
- 游标仍不是签名令牌：客户端可以伪造 `t`/`i` 跳到任意记录，但只能读管理员
  本就有权读取的数据；防篡改不在本 ADR 范围。
- 没有总数/导出/前端：需要看全部结果时仍要翻页；CSV 与总数留在待定。
- 明细表方案仍可用：如果未来恢复写入量或反查 QPS 明显上升，可以再加
  `(session_id, audit_id)` 明细表，当前不预建。

## 5. 验证

- 默认 **494 passed + 40 skipped**；真实 Postgres **531 passed + 3 skipped**；
  Postgres + Redis **534 passed**。
- `ruff check` / `ruff format --check`（193 files）/ `mypy app`（112 files）通过；
  前端未改，沿用 **81 tests / 16 files**、`oxlint` 0/0、`oxfmt --check` 76 files、
  `pnpm build`。
- API：同一 `sess_a` 的两次恢复 + 一次 `sess_b`，`session_id=sess_a&limit=1`
  翻两页后空页 `next_cursor=null`；`session_id=sess_missing` 返回空列表；
  带过滤游标换 `session_id` 400；ADR-0060 旧游标（无 `s`）在无过滤请求中仍可用；
  `session_id` 65 字符 422。
- 存储契约（内存 + Postgres）：`session_id="sess_drop2"` 只命中对应批次，
  不存在的 session 返回空。
- 迁移 `0020` 往返：`upgrade head` → `alembic check` → `downgrade 0019` →
  `upgrade head` 通过；无数据回填。
- 无前端改动；审批/审计其他分页行为未变。

## 6. 待定

- 审计列表 CSV 导出与总数；
- 前端管理页（当前只有 admin API）；
- 游标签名/过期（防伪造跳记录，当前内网管理接口可接受）；
- 如果恢复写入量或按 session 反查 QPS 上升，评估明细表
  `(session_id, audit_id)` 替换 JSONB GIN；
- 审计行是否记录请求中未恢复的 id（当前只存实际恢复的 id 与计数）。
