# ADR-0036：一次取回一页会话详情（批量读模型）

- 状态：已采纳
- 日期：2026-11-12
- 相关：[ADR-0030](0030-session-list.md)（会话列表）、[ADR-0031](0031-run-citations-replay.md)（引用快照）、
  [ADR-0035](0035-run-timeline-replay.md)（运行过程回放）

## 背景

打开一个 20 轮的历史会话，前端要发 **1 + 20 + 20** 次请求：会话列表 1 次、
20 条 run 详情各 1 次、20 次事件回放再各 1 次。run 越多越慢，移动端尤其明显。

三个接口本身都没错——`GET /runs/{id}` 返回正文与引用，`GET /runs/{id}/events`
返回运行过程，`GET /runs` 支持按会话过滤。问题在于**它们是为单条 run 设计的**，
组合起来就变成瀑布式 N+1。ADR-0030 与 ADR-0035 的「待定」里都记着这一点。

难点不在拼响应，而在批量后的两件事：

1. 可见性判定：每条 run 的引用文档要按当前角色重新校验（ADR-0022）。逐条查会变成
   20 次知识库查询，批量接口就失去了意义。
2. 运行过程：`timeline` 依赖事件，事件已清理或正文不可见时不能拼接（ADR-0035）。

## 备选方案

| 方案 | 否决原因 |
|---|---|
| 给 `GET /runs` 加 `include=detail` | 列表接口的职责被撑大；分页单位仍是 run，但响应体积与可见性规则都变了 |
| 前端并发拉 20 条详情 | 仍然是 N 次请求；HTTP/2 也省不掉服务端 20 次事件查询 |
| 先取 ids 再批量详情（两个接口） | 多一轮往返；ids 接口没有独立价值 |
| **`GET /sessions/{id}/runs` 会话级批量读模型（采纳）** | 一次返回一页 run 的正文/引用/过程；可见性与事件都批量查 |

## 决策

1. **新增 `GET /api/sessions/{session_id}/runs`**：一页 run 的完整历史视图。
   路径带 `session_id`，因为它表达的是「会话的一页」，而不是任意 run 集合。
2. **只读、无新表、无迁移**：仍然从 `runs` 与 `run_events` 投影；会话没有独立表
   （ADR-0030 的约束不变）。
3. **分页与 `/runs` 一致**：keyset 游标 `(started_at, run_id)`，`limit` 1–50 默认 20，
   取满才返回 `next_cursor`。items 按 `started_at DESC` 排列，与列表接口相同。
4. **不含 `model_calls`**：历史 transcript 不需要计量明细；需要时仍可走
   `GET /runs/{id}`。少查一张表，也避免把模型调用记录暴露给普通用户。
5. **批量可见性**：把整页 run 的 `cited_document_ids` 合并成一次
   `kb.visible_document_ids`；正文已按时间清理的 run 不参与判定（与
   `content_is_redacted` 语义一致）。被回收的 run 只影响自己，同页其他 run 正常返回。
6. **批量事件**：只对「回答可见且事件未清理」的 run 取事件；Postgres 用
   `row_number() over (partition by run_id order by seq)` 一次取回，每个 run 最多 500 条。
   前端仍然拿到每条 run 的 `timeline` / `timeline_available` / `timeline_truncated`。
7. **404 语义**：没有游标且查不到任何 run 时返回 404（不区分「不存在」与「别人的会话」，
   避免泄露存在性）；游标翻到空页返回 200 空列表，这样前端可以正常结束翻页。
8. **前端一次请求**：打开会话与「加载更早」都改调批量接口；`historyRequest` 竞态
   token 逻辑不变，`transcriptMessages` 的输入类型收敛为不含 `model_calls` 的
   `HistoryRun`。

## 后果

- 打开 20 轮会话从 41 次请求降到 1 次；加载更早从 41 次降到 1 次。
- 批量接口比单条详情返回更多字段（最多 50 条 run 的正文/引用/过程），响应可能达到
  数百 KB；当前没有单条 run 的字节上限，超大会话仍是已知风险。
- 为兼容单条详情，`get_run` 与批量接口共用 `_run_detail_payload`；单条详情的行为
  （包括 `model_calls`、404、503）保持不变。
- 事件读取仍是 500 条/run 的上限；极端长的 run 会截断运行过程，并置
  `timeline_truncated=true`。
- 会话不存在时批量接口返回 404，而 `/runs?session_id=` 对未知会话返回空列表；
  两个接口语义不同是有意的——批量接口的路径本身声明了会话存在性。

## 验证

- 默认 `uv run pytest`：**443 passed + 32 skipped**；真实 Postgres 下
  **472 passed + 3 skipped**，再加 Redis 为 **475 passed**。
- `ruff check` / `ruff format --check`（176 files）/ `mypy app`（106 files）通过。
- 前端 `tsc --noEmit`、`vitest` **65 tests / 13 files**、`oxlint` 0/0、
  `oxfmt --check`（62 files）、`pnpm build` 通过。
- 新增接口测试覆盖：批量详情含引用/运行过程且不含 `model_calls`；别人的会话与
  不存在的会话 404；`limit` / 游标翻页；游标越界返回 200 空页；同页中受限 run
  被单独回收、公开 run 不受影响。
- 未重跑检索/多轮评测：未改检索、提示词与多轮历史。

## 待定

- 单条 run 的响应字节上限（正文与工具结果都可能很大）。
- 批量接口是否支持按状态过滤、只取摘要（管理页/审计场景）。
- 更早轮次的一次性全量导出（当前仍是游标翻页）。
- 若前端需要「跳到某一轮」，需要按 run_id 定位的接口，而不是按时间游标。
