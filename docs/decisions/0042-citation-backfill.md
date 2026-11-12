# ADR-0042：历史引用快照回填（CLI）

- 状态：已采纳
- 日期：2026-11-12
- 相关：[ADR-0031](0031-run-citations-replay.md)、[ADR-0023](0023-run-content-retention.md)、[ADR-0021](0021-data-retention.md)

## 1. 背景

ADR-0031 给 `runs` 加了 `citations` JSONB，历史会话能还原引用角标。但快照是
从上线后的 `message.completed` 事件投影出来的：更早的 run 只有事件里的引用、
没有投影列，侧栏不出角标，详情接口返回 `[]`。README 与 ADR-0031 都把这个
缺口写成「迁移前的旧 run 不回填」。

事件表里其实还留着这些 run 的 `message.completed`（只要没到
`ONCALL_EVENT_RETENTION_DAYS`）。补一个**一次性、可重复执行**的运维回填，
比让旧会话永久缺角标更完整；同时不引入后台任务、不改变请求路径，
也不改变 ADR-0021/0023 的保留语义。

## 2. 备选方案

| 方案 | 否决理由 |
|---|---|
| 读取时按需从事件重建 | 每次打开历史会话都多一次事件扫描；GET 带写操作，多副本/重放语义复杂 |
| 放在迁移 `0015` 里做数据回填 | 迁移已发布；数据回填不可重复执行，且大表迁移会长时间锁表 |
| 定时后台任务持续回填 | 旧数据是一次性缺口；常驻任务为几十行数据增加运维面 |
| 从 `cited_document_ids` 反推 | 只有文档 id，没有标题/片段/页码，补不出可预览的角标 |
| **opt-in CLI（采纳）** | 运维显式执行，可 dry-run、可分批、可重复；不改运行时与保留策略 |

## 3. 决策

1. **新命令**：`make backfill-citations` / `python -m app.cli backfill-citations`，
   支持 `--dry-run` 与 `--limit`（默认 100，必须 ≥ 1）。JSON 输出
   `scanned` / `filled` / `skipped_no_citations` / `dry_run`。
2. **候选条件**：`citations == []`、`content_pruned_at is None`、
   `events_pruned_at is None`、`output is not None`。正文已清理的 run 不回填——
   快照是回答内容，不能比正文活得久（ADR-0023）；事件已清理的 run 没有重建来源。
   按 `started_at, run_id` 升序取一批，重复执行时自然向前推进。
3. **重建来源**：`store.events_for_runs` 批量取事件，取每个 run **最后一条**
   `message.completed`；复用 `_citation_snapshot` 的清洗规则（只保留已知字段、
   `title`/`heading` 200、`snippet` 500、最多 50 条、跳过没有 `document_id` 的条目）。
   没有该事件或 citations 为空/不可用的 run 计入 `skipped_no_citations`。
4. **条件写入**：新增 `RunStore.set_citations`，只在 `citations` 仍为空时写入
   （PG 用 `UPDATE ... WHERE jsonb_array_length(citations) = 0 RETURNING id`）。
   已回填/并发写入的 run 不会被覆盖；返回 False 不视为错误。
5. **批量读取**：新增 `RunStore.list_runs_without_citations`，PG 用
   `jsonb_array_length(citations) = 0` 过滤；不为回填加索引——这是低频运维扫描。
6. **不改变读路径**：回填出的快照仍走 `GET /runs/{id}` 的可见性与正文保留过滤
   （ADR-0022/0023）；回填不会让已回收的引用重新可见。
7. **可重复执行**：写过快照的 run 不再进入候选；dry-run 不写库。

## 4. 后果

- 事件仍保留的旧 run 能在运维执行后恢复角标；事件已清理的 run 仍然补不出，
  这与「事件是回放唯一真相」一致。
- 回填是逐 run 条件更新，并发打开会话不会读到半成品；重复执行无副作用。
- 一次最多扫描 `--limit` 场，大库需要分多次跑；没有进度游标，靠候选集合自然收敛。
- 不新增表、不新增迁移（schema 仍到 `0017`），前端无改动。

## 5. 验证

- 默认 `pytest`：**468 passed + 35 skipped**（新增 4 条内存用例；PG 用例条件跳过）。
- 真实 Postgres：`test_citation_backfill.py` 全绿；全量 **500 passed + 3 skipped**。
- `ruff check` 通过、`ruff format --check` 186 files、`mypy app` 110 files。
- CLI：`backfill-citations --dry-run` 输出四个字段且不写库；重复执行后 `scanned`
  归零。前端未改，仍 65 tests / 13 files。

## 6. 待定

- 大库上的分批游标与进度输出（当前靠 `--limit` + 候选集合收敛）。
- 按用户/会话/时间范围过滤。
- 自动定时回填（与「一次性缺口」的判断相悖，暂不做）。
- 运维操作审计（谁在何时跑了回填、影响多少场 run）。
