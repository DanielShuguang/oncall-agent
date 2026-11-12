# ADR-0033：会话列表与历史轮次分页

- 状态：已采纳
- 日期：2026-11-12

## 背景

ADR-0030 把会话列表做成了 `runs.session_id` 的投影，但第一版留了两个明确的边界：

- `GET /sessions` 的 `next_cursor` 固定为 `null`，只能看到最近 20 个会话；
- 打开历史会话时只取最近 20 条 run，更早的轮次没有入口。

`docs/07-frontend-design.md` 也写着「虚拟滚动仍未做」，但那是渲染层的问题；这里的缺口是
**数据取不全**：一个用了几个月的用户，最早的会话和会话里最早的问题会永久看不到。
会话表投影本身复用了 `idx_runs_user_session_time`，排序键 `(user_id, session_id,
started_at DESC)` 足够支撑 keyset，不需要新表或新迁移。

## 备选方案

| 方案 | 否决理由 |
|---|---|
| 新建 `sessions` 表，列表直接查表 | 引入写放大与一致性维护；投影已经能算，且没有标题以外的可变字段 |
| `offset` 分页 | 新 run 会把会话移到前面，翻页时重复/跳过比 keyset 更严重；深翻还要扫过前面所有行 |
| 前端一次拉全量 | 无上限；会话数随使用线性增长，迟早拖垮首屏 |
| 只按 `updated_at` 做游标 | 同一毫秒/同一时刻多个会话会漏掉或重复；必须带 `session_id` 兜底 |
| 按会话逐条拉完整历史（不分页） | 老会话可能有上百轮，一次拉全量会把详情接口打爆 |
| **采纳：keyset `(updated_at, session_id)` + 会话内沿用 `/runs` 游标** | 与现有索引、现有 `/runs` 分页形状一致；代价是翻页不保证快照一致性（见下） |

## 决策

1. **不建表、无迁移**。`RunStore.list_sessions` 增加可选的
   `before_updated_at` / `before_session_id`；内存实现按排序后的
   `(updated_at, session_id)` 比较，Postgres 在聚合后加 `HAVING`：
   `max(started_at) < before_updated_at OR (max(started_at) = before_updated_at AND session_id < before_session_id)`。
2. **游标是最后一行，不是页码**。排序键为 `(max(started_at) DESC, session_id DESC)`；
   `next_cursor` 只在当前页取满 `limit` 时返回，否则为 `null`。
3. **游标对前端不透明**：base64url(JSON `{"t": updated_at ISO, "s": session_id}`)。
   不用 `|` 拼接，因为 `session_id` 由客户端生成（1–64 字符），可能包含分隔符。
   解码失败、缺字段、时间无时区、`session_id` 越界统一返回
   `400 {"code":"INVALID_CURSOR"}`，不静默从头开始。
4. **会话内更早轮次复用 `/runs` 的游标**：`GET /runs?session_id=...&cursor=...`
   已经按 `(started_at, run_id)` 倒序分页；前端把「加载更早的对话」拿到的详情
   转成 transcript 后**插到现有消息前面**（`prependHistory`），不改变当前会话。
5. **一致性口径**：新 run 会把会话移到列表前面，翻页途中可能重复或跳过一页；
   刷新即从第一页重置。这是 keyset + 实时聚合的已知代价，不做快照/去重。
6. **前端两个「加载更多」**：会话栏底部「加载更多会话」，消息区顶部「加载更早的对话」；
   首屏仍是 20 个会话、每个 20 轮，不改变「继续对话」沿用 `session_id` 的语义。
   失败时写侧栏错误、保留已加载内容，不清空列表。
7. **虚拟滚动仍未做**：分页解决「取不到」，不解决「一次渲染很多条」；长会话仍直接渲染，
   留到后续单独处理。

## 后果

- 会话列表和会话内历史都可以一直往前翻，不再受 20 条限制。
- 没有新表、新索引、新迁移；`/sessions` 与 `/runs` 的分页形状保持一致，前端两处复用
  同一套 `next_cursor` 语义。
- 翻页期间若有新 run，用户可能看到重复项或漏掉刚被挤到前面的那一页；刷新可恢复。
- 游标只是位置编码，不签名、不加密：伪造最多让调用者看到自己更早的会话，不越权。
- 每个会话的首屏仍只取 20 轮；更早轮次需要用户主动点一次，不会自动全量加载。

## 验证

- 默认 `uv run pytest`：**428 passed + 31 skipped**。
- 真实 Postgres（pgserver 临时实例）：**456 passed + 3 skipped**（两条 Redis 账本用例条件跳过）。
- 再加 Redis：**459 passed**。
- 新增/修改：`tests/test_sessions_api.py` 3 条（游标翻页、非法游标 400、会话内更早 run）、
  `tests/test_store_contract.py` 的 `_exercise_sessions` 增加 keyset 断言（内存与 PG 共用）。
- `ruff check` / `ruff format --check`（171 files）/ `mypy app`（104 files）通过。
- 前端：`tsc --noEmit`、`pnpm test` **64 tests / 13 files**、`oxlint` 0/0、`oxfmt --check`
  69 files、`pnpm build` 成功（306ms）。
- 没有 SQL 迁移；检索、提示词、多轮判定未改，未重跑 RAG 与多轮评测。

## 待定

- 会话搜索已由 [ADR-0039](0039-session-search.md) 实现（只搜投影标题、本人、大小写不敏感
  子串）；重命名后来由 [ADR-0040](0040-session-rename.md) 补上；删除、未读标记仍需要新的产品语义，v1 不做。
- 翻页去重：如果要「翻页期间新 run 不造成重复」，需要记录翻页起点或返回稳定快照，
  成本明显高于收益，暂不做。
- 消息虚拟滚动：与分页正交，长会话仍可能一次渲染上百条消息。
- 游标签名/加密：当前只编码位置，伪造只能看到自己的数据；若将来跨用户共享游标再考虑。
- 每会话更早轮次的自动加载阈值（如滚到顶部自动加载）暂不做，保留显式按钮。
