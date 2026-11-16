# ADR-0082：会话置顶审计列表游标分页

## 背景

ADR-0081 新增了只读接口 `GET /admin/session-pins`，按 `(created_at, id)` 倒序
返回置顶/取消置顶审计，但只有 `limit`（1–200 默认 50），没有游标。审计会持续
增长，超过 200 条后更早的记录在管理端不可达；把 `limit` 调大只是把同一个问题
往后推。

审批列表（ADR-0052）、恢复审计列表（ADR-0060）已经采用 keyset 游标；置顶审计
同样按 `(created_at, id)` 倒序，适合复用同一套做法。

## 备选方案

| 方案 | 结论 |
|---|---|
| 只把 `limit` 上限提高 | 仍然有界，历史记录依旧不可达 |
| offset / 页码 | 翻页期间新增记录会导致重复/跳过，且需要总数才能显示页码 |
| 单 `created_at` 游标 | 同一时间戳的多条审计会漏或重 |
| 服务端保存游标状态 | 引入会话状态与过期问题，收益不足 |
| keyset `(created_at, id)` + 过滤绑定 | 采纳 |

## 决策

1. 排序与游标键都是 `(created_at, id)` 倒序；`id` 只是同时间戳的 tiebreaker。
2. 查询参数新增 `cursor`（最长 512），`limit` 仍为 1–200 默认 50；不接收
   `offset`/页码。
3. 游标是 base64url JSON：
   - `t`：`created_at` 的 ISO 8601 时间；
   - `i`：审计 UUID；
   - `u`/`s`/`a`：仅当本次请求带 `user_id`/`session_id`/`action` 时出现。
   服务端严格校验键集合与值；换过滤条件复用旧游标返回
   `400 INVALID_CURSOR`，不静默跳到另一组结果。
4. 只有取满 `limit` 才返回 `next_cursor`；未取满为 `null`（下一页为空）。
5. 取满时即使已经是最后一页也仍给游标，下一页返回空数组和 `null`；不在
   “取满且没有更多”时做额外探测。
6. 不新增迁移/索引：现有 `(created_at)` 与 `(user_id, created_at DESC)` 足以
   支撑当前量级；如果审计量变大，再评估 `(created_at, id)` 复合索引。
7. 不做导出、前端页面、总数/跳页；保留清理也仍未接入。

## 后果

- 翻页期间如果有新的置顶/取消置顶写入，旧游标之后的页可能重复或跳过记录；
  审计列表没有稳定快照，这是可接受的只读视图语义。
- 没有总数，管理端只能「加载更多」。
- 游标绑定过滤条件，换人/换会话/换动作必须从第一页重新拉取；旧游标会失效一次。
- 分页不改变审计写入语义：只有显式状态变化才写，隐藏/恢复清理不写。

## 验证

- 默认 `pytest`：511 passed + 40 skipped。
- 真实 PostgreSQL：548 passed + 3 skipped。
- PostgreSQL + Redis：551 passed。
- `ruff check` / `ruff format --check` 202 files / `mypy app` 116 files。
- 前端未改，沿用 114 tests / 24 files。
- 覆盖：API 两页翻完、空页 `next_cursor=null`、非法游标 400、换过滤复用旧游标
  400；store 内存/PG 契约按 `(created_at, id)` 翻完不重不漏。

## 待定

- 审计保留期与 `RetentionSweeper` 接入。
- 导出 CSV、前端管理页、总数/跳页。
- 审计量变大后的 `(created_at, id)` 复合索引与查询计划。
