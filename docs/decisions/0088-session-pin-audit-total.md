# ADR-0088：置顶审计列表首屏总数

## 背景

置顶审计列表（ADR-0085）支持用户/会话/动作/日期过滤与 keyset 分页
（ADR-0082/0086），页面只显示「已加载 N 条」。管理员知道当前页有几条，
但不知道同过滤条件下总共有多少条；要得到总数只能一直翻到最后一页。

审批列表（ADR-0057）与恢复审计列表（ADR-0064）已经采用「第一页附
`total`、后续页为 `null`」的口径，本 ADR 把同一口径扩展到置顶审计。

## 备选方案

| 方案 | 否决原因 |
|---|---|
| 每页都返回 total | 每次加载更多多一次 COUNT，且翻页期间 total 会变 |
| 独立 `GET /admin/session-pins/count` | 列表与计数两个请求、两套 loading，容易短暂不一致 |
| 前端遍历所有页再计数 | 数据量大时不可接受，且会放大分页请求 |
| 只返回当前页条数 | 不能回答「总共有多少」；本 ADR 要解决的正是这个 |

## 决策

1. **只给第一页**：`GET /admin/session-pins` 在无 `cursor` 时返回
   `total`（int）；带 `cursor` 的后续页返回 `null`。旧后端无字段时前端
   只显示「已加载 N 条」。
2. **过滤口径一致**：`total` 与列表使用同一组 `user_id`/`session_id`/
   `action`/`created_from`/`created_to` 条件；日期仍是 UTC 半开窗口。
   计数不接收 `cursor`，不按游标截断。
3. **存储实现**：`RunStore.count_session_pin_audits` 与
   `list_session_pin_audits` 共用过滤；内存遍历 `_session_pin_audits`，
   Postgres `select(count()).select_from(session_pin_audits)` 加同一组
   `where`。复用现有索引，无迁移。
4. **失败处理**：计数和列表在同一个 `try` 中；任一失败返回 503
   `DATABASE_UNAVAILABLE`，不返回「列表成功但 total 缺失」的半成品。
5. **前端展示**：首屏成功后显示「共 N 条 · 已加载 M 条」；加载更多只增加
   M，不重复请求 total；切换过滤时立即清空 total 与列表，避免旧总数
   配新过滤条件。
6. **不做**：页码/跳页、缓存总数、异步计数、按日统计复用 total
   （按日统计见 ADR-0087）。

## 后果

- 第一页多一次 COUNT；列表每页最多 200 条，审计表有 365 天保留上限，
  当前量级可接受。
- `total` 与列表是两次查询，并发写入时可能相差一条；页面不承诺严格
  同一快照，这一点与 ADR-0057/0064 一致。
- 旧后端没有 `total` 字段时，前端降级为只显示已加载条数，不影响列表。

## 验证

- 后端：默认 **516 passed + 40 skipped**；Postgres **553 passed + 3 skipped**；
  Postgres + Redis **556 passed**；`ruff check` / `ruff format --check`
  200 files / `mypy app` 116 files。
- 前端：tsc、**119 tests / 25 files**、oxlint 0/0（88 files/231 rules）、
  `oxfmt --check` 96 files、`pnpm build` 2900 modules / 751ms。
- 测试覆盖：第一页 total、后续页 null、过滤后 total、日期范围 total、
  空过滤 0、计数失败 503。

## 待定

- 是否提供页码/跳页；当前仍是 keyset「加载更多」。
- 是否缓存 total 或使用估算值；当前每次首屏实时 COUNT。
- 是否在管理页顶部展示总数卡片；当前只放在列表头。
