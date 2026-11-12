# 0030 会话列表与历史会话继续

- 状态：已采纳
- 日期：2026-11-11
- 关联：[docs/03](../03-api-contract.md)、[docs/07](../07-frontend-design.md)、[ADR-0020](0020-multi-turn-context.md)、[ADR-0023](0023-run-content-retention.md)

## 背景

多轮上下文（ADR-0020）从 W6 后补起已经可用：服务端按 `user_id + session_id` 取最近几轮，
前端每次发送带同一个 `session_id`。但前端只有一个「当前会话」——刷新页面、换设备、
关掉标签页，都只能从 `sess_xxx` 的新 ID 重新开始；此前聊过的内容仍然在 `runs` 表里，
却没有入口回到那段对话。`docs/07` §5 一直把「会话列表与消息虚拟滚动」列为未实现。

缺的不是存储：`runs.session_id` 从第一天就是非空字段，`idx_runs_user_session_time`
（`user_id, session_id, started_at DESC`）也已存在。缺的是「把已有 run 投影成会话」的
只读接口，以及在打开历史会话后能**继续**用同一个 `session_id` 提问的前端状态切换。

## 备选方案

| 方案 | 结论 | 原因 |
|---|---|---|
| 新建 `sessions` 表（标题、更新时间、归档标记） | 否决 | 与 `runs` 重复，任何 run 写入都要同步维护；还要处理清理、级联与迁移，收益只是省一次聚合 |
| 前端 localStorage 存会话列表 | 否决 | 换设备/清缓存即丢；权限与保留清理都以服务端为准，本地缓存会展示已被回收的会话 |
| 列表用 `runs` 全量拉回前端再分组 | 否决 | 拉到的是 run 而不是会话，条数不可控；分页语义也不对 |
| v1 直接做游标分页 + 虚拟滚动 | 否决（延后） | 20 个会话的侧栏不需要虚拟滚动；游标分页等真实数据量再补，避免先写一套没有调用方的契约 |
| **按 `session_id` 聚合 `runs` + 只读 transcript + 切回同一 session** | **采纳** | 无新表、无迁移；历史内容本来就在，继续对话复用既有多轮链路 |

## 决策

1. **会话不建表**：会话是 `runs` 的投影，键是 `(user_id, session_id)`。没有 run 就没有会话，
   因此不需要额外的清理任务；事件/正文按 ADR-0021/0023 清理后，会话摘要仍然可用。
2. **聚合口径**：`RunStore.list_sessions(user_id, limit=20)` 按 `session_id` 分组，
   `started_at = min(run.started_at)`、`updated_at = max(run.started_at)`、
   `run_count = count(*)`；按 `(updated_at DESC, session_id DESC)` 排序，避免同一时刻的顺序抖动。
   复用 `idx_runs_user_session_time`，不新增索引、**无迁移**。
3. **标题取最早一条非空 `input`**：正文按 ADR-0023 过期清空后标题为 `NULL`，前端显示「无标题」，
   会话本身仍然出现在列表里——不能因为标题没了就把用户的历史删掉。接口层把标题压成单行并截到
   60 字符（超出加 `…`），侧栏不展示长文。
4. **`GET /api/sessions`**：只读当前用户，`limit` 1–50 默认 20；返回
   `{items: [{session_id, title, run_count, started_at, updated_at}], next_cursor: null}`。
   v1 不做游标、重命名、删除、共享；`next_cursor` 固定 `null`，保持与 `/runs` 相同形状，
   以后加分页时不用改客户端解析。没有 admin 旁路——会话是个人对话，管理员也没有必要按用户翻。
5. **按会话取历史**：`GET /api/runs` 增加可选 `session_id` 过滤（仍只查自己）。
   前端打开会话时取最近 20 条 run，再并发取详情；更早的轮次不在 v1 范围。
6. **只读 transcript**：详情里的 `input` / `output` 按时间顺序配成 user/assistant 气泡；
   `content_pruned_at` 显示「正文已过保留期」、`content_redacted` 显示「引用文档已不可见」、
   未结束的 run 显示「还没有结束」、失败显示「没有生成回答」。回看不是回放：不重放实时工具卡片
   与审批操作，也不重新执行任何写操作；只读运行过程由 ADR-0035 从事件投影。
7. **继续对话**：点击历史会话后，前端把 `session_id` 切到该会话并把 transcript 灌进消息列表；
   下一次发送沿用这个 `session_id`，服务端按 ADR-0020 的 `recent_turns` 续上下文。前端不自己
   拼历史消息发给模型——上下文仍由服务端投影，前端 transcript 只用于展示。
   发送完成后刷新一次会话列表，让标题/轮数/更新时间即时反映。
8. **不缓存到浏览器**：会话列表每次进页面从服务端拉；只存在内存里。换设备、退出、正文过期
   都自然一致。v1 不做虚拟滚动（20 个会话用不上），也不做侧栏折叠/移动端抽屉。

## 后果

- 刷新页面不再等于「开新会话」：用户可以在侧栏点回最近 20 个会话，历史问答只读可见，
  点「继续」后回到同一 `session_id`，多轮上下文与保留清理都沿用既有规则。
- 会话列表最多 20 个、每个会话最多回看 20 轮；更早的内容还在库里，只是没有入口。
- 标题来自最早一条输入，不会随对话推进自动改名；用户改标题已由 [ADR-0040](0040-session-rename.md) 补上，从列表移除已由 [ADR-0041](0041-session-remove.md) 补上（软移除，不删数据）。
- 正文过期后会话标题为 `NULL`、历史气泡变成占位说明，但会话与轮数仍在——这是有意的：
  保留策略清理的是内容，不是「你曾经问过」这个事实。
- 列表查询多一次 `runs` 聚合（带索引），与 `/runs` 一样在库不可用时返回 503，
  不会静默返回空列表（否则会显示成「你没有历史会话」）。
- 前端多一次「列表 + 按会话取详情」的请求链；打开历史会话时最多 21 个请求（20 条 run 详情并发），
  在演示与私有化规模下可接受。后续已由 [ADR-0036](0036-session-detail-batch.md) 补上批量详情接口，
  现在打开一页会话只需一次请求。

## 验证

- 后端默认：`uv run pytest -p no:warnings` → **419 passed, 31 skipped**（改前 413 + 31）。
- 真实 Postgres（pgserver 临时实例）：**447 passed, 3 skipped**（改前 441 + 3）；
  跳过的 3 条仍是 Redis 账本/快照用例。
- 新增测试：
  - `server/tests/test_sessions_api.py`：按会话聚合/排序、只返回本人、limit 校验、
    标题空回退与 60 字符截断、`?session_id=` 过滤、库故障 503；
  - `server/tests/test_store_contract.py` 的 `_exercise_sessions`：内存与 PG 共用，
    覆盖聚合、倒序、标题回退、limit、own-only 与按会话过滤；
  - `web/src/features/chat/history.test.ts`：transcript 排序、清理/回收/未结束/失败占位；
  - `web/src/features/chat/store.test.ts`：`switchSession` 换 ID、灌 transcript、清旧运行态，
    继续发送沿用历史 `session_id`。
- `ruff check` / `ruff format --check`（167 files）/ `mypy app`（103 files）通过。
- 前端：`tsc --noEmit`、`vitest` **63 tests / 13 files**、`oxlint` 0/0（61 files）、
  `oxfmt --check`（69 files）、`pnpm build` 成功。
- 无 SQL 迁移；检索 / 提示词 / 多轮历史未改，未重跑 RAG 与多轮评测。

## 待定

- 会话分页（`next_cursor` 目前恒为 `null`）与超过 20 个会话后的加载方式。
- 重命名（已由 [ADR-0040](0040-session-rename.md) 兑现）、从列表移除（已由 [ADR-0041](0041-session-remove.md) 以软移除兑现；硬删除未做，仍需回答保留与审计口径）、置顶会话。
- 消息虚拟滚动与移动端抽屉；等真实会话长度/设备数据再决定。
- 会话内更早轮次的分页回看（现在只取最近 20 条 run）。
- 批量详情接口：已由 [ADR-0036](0036-session-detail-batch.md) 兑现
  （`GET /sessions/{session_id}/runs`，一页会话一次请求）。
- 只读 transcript 的历史工具/审批由 [ADR-0035](0035-run-timeline-replay.md) 以折叠区投影补上
  （最多 20 项、跟随回答可见性）；引用角标已由 [ADR-0031](0031-run-citations-replay.md)
  补上（`runs.citations` 快照）。
- 管理员/审计视角的会话检索（需要先有明确的合规边界，不能默认给 admin 开旁路）。
