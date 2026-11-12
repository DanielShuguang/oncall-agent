# ADR-0031：会话历史的引用回放

- 状态：已采纳（2026-11-12）
- 相关：[ADR-0018](0018-citation-fulltext-preview.md)、[ADR-0021](0021-data-retention.md)、
  [ADR-0022](0022-run-content-visibility.md)、[ADR-0023](0023-run-content-retention.md)、
  [ADR-0030](0030-session-list.md)

## 背景

ADR-0030 让左侧会话列表可以回看历史，但 transcript 只有 `input`/`output` 两段文本：
当时的引用角标（`[1] 薪酬制度 p.3`）没有还原，点不进全文预览。原因不是前端做不到，
而是**读路径上没有引用快照**：

- `GET /runs/{id}` 只返回 `output`，不返回引用；
- 完整引用在 `message.completed.citations` 事件里，但事件会被 ADR-0021 按保留期整场删除；
- `runs.cited_document_ids` 只存文档 id（ADR-0022 做权限回收用），没有 `chunk_id`/`ord`/
  `title`/`snippet`，无法还原角标，也不能在文档更新后重新定位到当时的切片。

所以这个缺口是「历史会话只能读文字、不能溯源」。

## 备选方案

| 方案 | 结论 |
|---|---|
| 每次打开会话时读 `message.completed` 事件重建 | 否决。打开一个 20 轮的会话要再发 20 次事件查询；事件被清理后彻底失效 |
| 只存 `cited_document_ids`，打开时现查知识库 | 否决。知识库没有「当时的 chunk 顺序/摘录」，文档更新还会对不上 |
| 新建 `run_citations` 表 | 否决。多一张表与一套清理逻辑，收益只是避免一行 JSONB |
| `runs.citations` JSONB，随 `message.completed` 写入 | **采纳**。读详情一次取回，事件清了也还在 |

## 决策

1. **写入**：`build_run_patch` 在 `message.completed` 时同时投影 `citations` 与
   `cited_document_ids`。快照只保留角标需要的字段（`chunk_id`、`document_id`、`ord`、
   `title`、`heading`、`snippet`、`page`），类型不对的字段退回默认值，没有
   `document_id` 的条目跳过，文本字段超长截断（`title`/`heading` 200、
   `snippet` 500），最多 50 条。空数组表示「这轮明确没有引用」，与
   「事件没带这个字段」区分。
2. **读取**：`GET /runs/{id}` 增加 `citations`。只有在 `output` 可见且正文未过期时返回；
   `output` 缺失、`content_redacted` 或 `content_pruned_at` 非空时返回 `[]`——引用片段
   是回答内容，不能比正文活得更久。
3. **保留**：正文按 ADR-0023 清空时，`citations` 一并置空；`cited_document_ids`
   不清，权限回收（ADR-0022）仍然需要它。清理是同一个 UPDATE，不新增后台任务。
4. **前端**：`transcriptMessages` 只在回答可见时把 `citations` 挂到 assistant 消息上，
   复用现有角标与 `CitationPreviewDialog`；预览请求仍走 `/kb/preview`，按**当前**
   角色校验，fail-closed 口径不变。
5. **不扩大回放范围**：仍然不回放工具结果、审批卡片与步骤条；这些是运行过程，
   不是会话内容（ADR-0030）。
6. **无新接口、无新表**：只加一个 JSONB 列（迁移 `0014`）。历史 run 默认不回填；
   事件仍在时可用 ADR-0042 的 `backfill-citations` 从事件重建，但不作为迁移的一部分。

## 后果

- 每个有引用的 run 多存几 KB（默认最多 5 条、上限 50 条），换历史会话可溯源。
- 180 天后引用片段随正文一起消失，run 只留文档 id；这是有意的，不能把
  「正文已删」做成「片段还在」。
- 迁移前的历史 run `citations` 为 `[]`，打开旧会话没有角标；用户重新提问即可获得。
- 预览仍按当前权限：文档被收权后，角标会还原但点开预览会失败并回退到片段——
  片段本身也会因为整场 `content_redacted` 而不返回，两者口径一致。

## 验证

- 默认 `uv run pytest`：**422 passed + 31 skipped**（新增 3 条：快照清洗/上限、空数组与
  非数组、`output` 缺失时不返回引用）。
- 真实 Postgres（pgserver 临时实例）：**450 passed + 3 skipped**；`alembic upgrade head`
  → `alembic check` → `downgrade 0013` → `upgrade head` 往返无漂移。
- `ruff check` / `ruff format --check`（169 files）/ `mypy app`（103 files）通过。
- 前端 `tsc --noEmit`、`pnpm test` **63 tests / 13 files**、`oxlint` 0/0、
  `oxfmt --check`（69 files）通过。
- 检索、提示词、多轮判定未改，未重跑 RAG / 分类 / 多轮评测。

## 待定

- ✅ 历史 run 的一次性回填已由 [ADR-0042](0042-citation-backfill.md) 的 `backfill-citations` CLI 兑现；事件已清理的 run 仍补不出。
- 单条引用级的权限回收：现在一篇文档不可见就整场回收（ADR-0022），快照也是整场返回。
- 引用快照的体积上限与压缩；如果真实回答引用很多，可只存 `chunk_id` + `ord`，
  打开时再向知识库要标题/摘录。
- 是否把引用快照用于回答质量分析（引用命中率、死链率）。
