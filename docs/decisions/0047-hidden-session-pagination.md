# ADR-0047：已移除会话的分页与搜索

- 状态：已采纳（W6 后补）
- 日期：2026-11-13
- 关联：[ADR-0043](0043-hidden-session-restore.md)（已移除会话的查看与恢复）、
  [ADR-0039](0039-session-search.md)（会话列表标题搜索）、
  [ADR-0033](0033-session-history-pagination.md)（会话历史分页）

## 1. 背景

ADR-0043 的「已移除的会话」折叠区能列出被软移除的会话并恢复，但 v1 有两个明确的
限制：`GET /sessions/hidden` 最多返回 50 条，且没有搜索。软移除不会删 run，用户
误移除或长期使用后，这个列表会一直累积；只靠滚动找一条旧会话会越来越难。

主会话列表已经有标题搜索（ADR-0039）和 keyset 分页（ADR-0033），「已移除」视图
没有理由用另一套交互。缺口不在数据——`hidden_sessions`、`runs`、`session_titles`
都已经在库里——而在接口和前端。

## 2. 备选方案

| 方案 | 为什么不采纳 |
|---|---|
| 前端只在已加载的 50 条里过滤 | 搜索范围被首屏截断，找更早移除的会话仍然找不到；用户会以为「没有」 |
| 一次返回全部已移除会话 | 单用户长期使用会无界增长；与主列表的口径也不一致 |
| 新建搜索索引 / 物化视图 | 数据量是「单用户被移除会话」，远没到需要索引的量级；多一张表就多一处一致性负担 |
| 复用主列表接口加 `hidden=true` | 主列表与已移除视图的排序键不同（最近活动 vs 移除时间），参数化会把两种语义混在一个查询里 |
| **keyset 分页 + 标题搜索（采纳）** | 与主列表同口径、无迁移、查询计划简单；翻页只依赖 `(hidden_at, session_id)` |

## 3. 决策

1. `GET /api/sessions/hidden` 增加 `cursor` 与 `q`；`limit` 仍为 1–50、默认 50。
   `cursor` 编码 `(hidden_at, session_id)`，与主列表共用 base64url JSON 游标格式。
2. 排序不变：`hidden_at DESC, session_id DESC`。`hidden_at` 在重复移除时保留第一次
   时间（ADR-0041/0043），因此已加载页的游标不会因为再次移除同一个会话而失效。
3. 搜索与主列表同口径：大小写不敏感的子串，同时匹配显示标题（自定义标题优先，
   否则最早一条非空 `input`）与首条问题；**不搜回答正文**，也不搜工具结果/审批理由。
   这样「改名后新旧关键词都找得到」的语义在已移除视图里同样成立。
4. 只有当前页取满时才返回 `next_cursor`；下一页为空时 `next_cursor` 为 `null`。
   翻页期间恢复/移除会话会让列表变化，可能重复或跳过一页；重新展开即重置。
5. 非法游标返回 `400 INVALID_CURSOR`；`q` 超过 100 字符返回 422；库不可用仍返回
   `503 DATABASE_UNAVAILABLE`，不把故障显示成「没有已移除的会话」。
6. 存储层给 `RunStore.list_hidden_sessions` 增加
   `before_hidden_at`、`before_session_id`、`query` 三个可选参数；内存实现与
   Postgres 实现保持同一排序、同一游标语义、同一标题口径。
7. 前端折叠区增加搜索框与「加载更多」；请求仍受 `hiddenRequest` token 保护，
   旧响应不会覆盖新关键词/新页的结果。恢复、移除、关闭折叠区都会让在途请求失效。

## 4. 后果

- 已移除视图与主列表终于用同一套「标题搜索 + keyset 翻页」交互；误移除的会话再早
  也能找回来。
- 没有迁移、没有新索引：查询仍按 `hidden_sessions.user_id` 过滤后聚合 `runs`，
  数据量是单用户级；真实量级变大时再考虑给 `hidden_at` 加索引。
- 搜索仍然只覆盖标题，不覆盖正文。想找「聊过某个词」的会话，主列表和已移除视图
  都做不到——这是 ADR-0039 就明确留下的边界，不是本轮引入的。
- 翻页不承诺稳定快照：与主列表一样，新移除/恢复会导致重复或跳过一页；刷新即重置。
- 恢复语义没有变化：只删 `hidden_sessions` 行，run/事件/审批/标题/引用快照都不动。

## 5. 验证

- 默认 `uv run pytest -p no:warnings`：**472 passed + 35 skipped**。
- 真实 Postgres（临时 pgserver）：**504 passed + 3 skipped**；Postgres + Redis：**507 passed**。
  契约用例覆盖内存与 PG 的 keyset 翻页、标题/首条问题双匹配、恢复后列表变化。
- `ruff check` 通过、`ruff format --check` **186 files**、`mypy app` **110 files**。
- 前端 `tsc --noEmit` 通过、**73 tests / 15 files**、`oxlint` 0/0（66 files、231 rules）、
  `oxfmt --check` **74 files**、`pnpm build` 通过。
- 无迁移（schema 仍 0017）、无新事件类型、无检索/提示词/多轮改动，未重跑评测。

## 6. 待定

- `hidden_sessions` 的孤儿行清理（run 行被手动删除时）仍未做。
- 管理员视角、按移除时间范围筛选；批量恢复已由 [ADR-0049](0049-hidden-session-batch-restore.md) 兑现。
- 已移除视图是否也需要「内容搜索」，取决于主列表内容搜索的取舍，当前不做。
- 真实数据量下的索引与查询计划（当前按单用户级数据设计）。
